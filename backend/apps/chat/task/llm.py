import concurrent
import json
import os
import traceback
import urllib.parse
import warnings
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime
from typing import Any, List, Optional, Union, Dict, Iterator

import orjson
import pandas as pd
import requests
import sqlparse
from langchain.chat_models.base import BaseChatModel
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, BaseMessageChunk
from sqlalchemy import and_, select
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlbot_xpack.config.model import SysArgModel
from sqlbot_xpack.custom_prompt.models.custom_prompt_model import CustomPromptTypeEnum
from apps.custom_prompt_version.runtime import find_published_custom_prompts
from sqlbot_xpack.license.license_manage import SQLBotLicenseUtil
from sqlmodel import Session

from apps.ai_model.model_factory import LLMConfig, LLMFactory, get_default_config
from apps.chat.clarification_util import (
    apply_user_resolution, attach_clarification_plan_and_progress, build_initial_clarification,
    clarification_limit_xml, get_time_range_resolved, increment_ask_count, is_time_factor,
    normalize_current, resolved_blocks_xml, should_force_finalize,
)
from apps.chat.id_schema_prefilter import (
    detect_id_clarification_needed,
    extract_numeric_ids,
    parse_id_fields_from_schema,
)
from apps.chat.balance_time_handler import MIXED_METRIC_KIND_HINT, classify_balance_time
from apps.chat.bluecard.layout import build_table_chart_config, plan_bluecard_result
from apps.chat.bluecard.field_aliases import (
    aliases_list,
    incomplete_fields,
    merge_aliases,
    parse_llm_alias_payload,
    resolve_dict_aliases,
)
from apps.chat.metric_kind_resolver import (
    MetricKindContext,
    build_metric_kind_context,
)
from apps.chat.sql_time_filter_validator import (
    extract_sql_table_names,
    resolve_time_role_fields_for_tables,
    sql_has_time_filter,
)
from apps.chat.time_config import get_query_earliest_date
from apps.chat.time_range_prefilter import (
    build_time_range_clarification,
    infer_time_range_from_question,
    question_has_explicit_time_constraint,
    question_has_time_constraint,
    question_time_range_xml,
)
from apps.chat.curd.chat import save_question, save_sql_answer, save_sql, \
    save_error_message, save_sql_exec_data, save_chart_answer, save_chart, \
    finish_record, save_analysis_answer, save_summary_answer, save_field_aliases, save_predict_answer, save_predict_data, \
    save_select_datasource_answer, save_recommend_question_answer, \
    get_old_questions, save_analysis_predict_record, rename_chat, get_chart_config, \
    get_chat_chart_data, list_generate_sql_logs, list_generate_chart_logs, start_log, end_log, \
    get_last_execute_sql_error, format_json_data, format_chart_fields, get_chat_brief_generate, get_chat_predict_data, \
    get_chat_chart_config, trigger_log_error, save_clarification_state, is_clarification_pending, \
    abandon_clarification, get_chat_record_by_id
from apps.chat.models.chat_model import ChatQuestion, ChatRecord, Chat, RenameChat, ChatLog, OperationEnum, \
    ChatFinishStep, AxisObj, SystemPromptMessage, HumanPromptMessage, AIPromptMessage
from apps.data_training.curd.data_training import get_training_template
from apps.datasource.crud.datasource import get_table_schema
from apps.datasource.crud.permission import get_row_permission_filters, is_normal_user
from apps.datasource.embedding.ds_embedding import get_ds_embedding
from apps.datasource.models.datasource import CoreDatasource
from apps.db.db import exec_sql, get_version, check_connection
from apps.system.crud.assistant import AssistantOutDs, AssistantOutDsFactory, get_assistant_ds
from apps.system.crud.parameter_manage import get_groups
from apps.system.schemas.system_schema import AssistantOutDsSchema
from apps.terminology.curd.terminology import get_terminology_template
from apps.terminology.metric_kind import SCENARIO_BALANCE_ONLY, SCENARIO_FLOW_ONLY, SCENARIO_MIXED, SCENARIO_NONE
from apps.extra_prompt.crud.extra_prompt import find_enabled_extra_prompt
from apps.extra_prompt.models.extra_prompt_model import ExtraPromptTypeEnum
from common.core.config import settings
from common.core.db import engine
from common.core.deps import CurrentAssistant, CurrentUser
from common.error import SingleMessageError, SQLBotDBError, ParseSQLResultError, SQLBotDBConnectionError, \
    ClarificationRequiredError
from common.utils.data_format import DataFormat
from common.utils.locale import I18n, I18nHelper
from common.utils.utils import SQLBotLogUtil, extract_nested_json, prepare_for_orjson

warnings.filterwarnings("ignore")

executor = ThreadPoolExecutor(max_workers=200)

dynamic_ds_types = [1, 3]
dynamic_subsql_prefix = 'select * from sqlbot_dynamic_temp_table_'

session_maker = scoped_session(sessionmaker(bind=engine, class_=Session))

i18n = I18n()


class LLMService:
    ds: CoreDatasource
    chat_question: ChatQuestion
    record: ChatRecord
    config: LLMConfig
    llm: BaseChatModel
    sql_message: List[Union[BaseMessage, dict[str, Any]]]
    chart_message: List[Union[BaseMessage, dict[str, Any]]]

    # session: Session = db_session
    current_user: CurrentUser
    current_assistant: Optional[CurrentAssistant] = None
    out_ds_instance: Optional[AssistantOutDs] = None
    change_title: bool = False

    generate_sql_logs: List[ChatLog]
    generate_chart_logs: List[ChatLog]
    current_logs: dict[OperationEnum, ChatLog]
    chunk_list: List[str]
    future: Future

    trans: I18nHelper = None

    last_execute_sql_error: str = None
    articles_number: int = 4

    enable_sql_row_limit: bool = settings.GENERATE_SQL_QUERY_LIMIT_ENABLED
    base_message_round_count_limit: int = settings.GENERATE_SQL_QUERY_HISTORY_ROUND_COUNT
    clarification_max_rounds: int = settings.CLARIFICATION_MAX_ROUNDS
    _force_clarification_finalize: bool = False
    _metric_kind_context: Optional[MetricKindContext] = None
    _balance_time_llm_hint: Optional[str] = None
    _needs_mixed_metric_hint: bool = False
    _inferred_time_range: Optional[dict] = None

    def __init__(self, session: Session, current_user: CurrentUser, chat_question: ChatQuestion,
                 current_assistant: Optional[CurrentAssistant] = None, no_reasoning: bool = False,
                 embedding: bool = False, config: LLMConfig = None):
        self.sql_message = []
        self.chart_message = []
        self.generate_sql_logs = []
        self.generate_chart_logs = []
        self.current_logs = {}
        self.chunk_list = []
        self.current_user = current_user
        self.current_assistant = current_assistant
        chat_id = chat_question.chat_id
        chat: Chat | None = session.get(Chat, chat_id)
        if not chat:
            raise SingleMessageError(f"Chat with id {chat_id} not found")
        ds: CoreDatasource | AssistantOutDsSchema | None = None
        if not chat.datasource and chat_question.datasource_id:
            _ds = session.get(CoreDatasource, chat_question.datasource_id)
            if _ds:
                if _ds.oid != current_user.oid:
                    raise SingleMessageError(
                        f"Datasource with id {chat_question.datasource_id} does not belong to current workspace")
                chat.datasource = _ds.id
                chat.engine_type = _ds.type_name
                # save chat
                session.add(chat)
                session.flush()
                session.refresh(chat)
                session.commit()

        if chat.datasource:
            # Get available datasource
            if current_assistant and current_assistant.type in dynamic_ds_types:
                self.out_ds_instance = AssistantOutDsFactory.get_instance(current_assistant)
                ds = self.out_ds_instance.get_ds(chat.datasource)
                if not ds:
                    raise SingleMessageError("No available datasource configuration found")
                chat_question.engine = ds.type + get_version(ds)
            else:
                ds = session.get(CoreDatasource, chat.datasource)
                if not ds:
                    raise SingleMessageError("No available datasource configuration found")
                chat_question.engine = (ds.type_name if ds.type != 'excel' else 'PostgreSQL') + get_version(ds)

        self.generate_sql_logs = list_generate_sql_logs(session=session, chart_id=chat_id)
        self.generate_chart_logs = list_generate_chart_logs(session=session, chart_id=chat_id)

        self.change_title = not get_chat_brief_generate(session=session, chat_id=chat_id)

        chat_question.lang = get_lang_name(current_user.language)
        self.trans = i18n(lang=current_user.language)

        self.ds = (
            ds if isinstance(ds, AssistantOutDsSchema) else CoreDatasource(**ds.model_dump())) if ds else None
        self.chat_question = chat_question
        self.config = config
        if no_reasoning:
            # only work while using qwen
            if self.config.additional_params:
                if self.config.additional_params.get('extra_body'):
                    if self.config.additional_params.get('extra_body').get('enable_thinking'):
                        del self.config.additional_params['extra_body']['enable_thinking']

        self.chat_question.ai_modal_id = self.config.model_id
        self.chat_question.ai_modal_name = self.config.model_name

        # Create LLM instance through factory
        llm_instance = LLMFactory.create_llm(self.config)
        self.llm = llm_instance.llm

        # get last_execute_sql_error
        last_execute_sql_error = get_last_execute_sql_error(session, self.chat_question.chat_id)
        if last_execute_sql_error:
            self.chat_question.error_msg = f'''<error-msg>
{last_execute_sql_error}
</error-msg>'''
        else:
            self.chat_question.error_msg = ''

    @classmethod
    async def create(cls, *args, **kwargs):
        config: LLMConfig = await get_default_config()
        instance = cls(*args, **kwargs, config=config)

        chat_params: list[SysArgModel] = await get_groups(args[0], "chat")
        for config in chat_params:
            if config.pkey == 'chat.limit_rows':
                if config.pval.lower().strip() == 'true':
                    instance.enable_sql_row_limit = True
                else:
                    instance.enable_sql_row_limit = False
            if config.pkey == 'chat.context_record_count':
                count_value = config.pval
                if count_value is None:
                    count_value = settings.GENERATE_SQL_QUERY_HISTORY_ROUND_COUNT
                count_value = int(count_value)
                if count_value < 0:
                    count_value = 0
                instance.base_message_round_count_limit = count_value
        return instance

    def is_running(self, timeout=0.5):
        try:
            r = concurrent.futures.wait([self.future], timeout)
            if len(r.not_done) > 0:
                return True
            else:
                return False
        except Exception as e:
            return True

    def init_messages(self, session: Session):

        self.choose_table_schema(session)

        last_sql_messages: List[dict[str, Any]] = self.generate_sql_logs[-1].messages if len(
            self.generate_sql_logs) > 0 else []
        if self.chat_question.regenerate_record_id:
            # filter record before regenerate_record_id
            _temp_log = next(
                filter(lambda obj: obj.pid == self.chat_question.regenerate_record_id, self.generate_sql_logs), None)
            last_sql_messages: List[dict[str, Any]] = _temp_log.messages if _temp_log else []

        # 排除所有的系统提示词
        last_sql_messages = [obj for obj in last_sql_messages if obj.get("sqlbot_system") != True]

        count_limit = self.base_message_round_count_limit

        self.sql_message = []
        # add sys prompt
        _system_templates = self.chat_question.sql_sys_question(self.ds.type, self.enable_sql_row_limit)
        self.sql_message.append(SystemPromptMessage(content=_system_templates['system']))
        self.sql_message.append(HumanPromptMessage(content=_system_templates['rules']))
        self.sql_message.append(
            AIPromptMessage(content='我已掌握所有规则，包括表结构、SQL规范、安全限制和输出格式，我会严格遵守这些规则。'))
        self.sql_message.append(HumanPromptMessage(content=_system_templates['schema']))
        self.sql_message.append(
            AIPromptMessage(content='我已确认您提供的数据库信息与表结构schema，我生成的SQL不会超出您提供的范围。'))
        if _system_templates.get('custom_prompt'):
            self.sql_message.append(HumanPromptMessage(content=_system_templates['custom_prompt']))
            self.sql_message.append(AIPromptMessage(content='我已确认您提供的额外信息，我会进行参考。'))

        # extra prompt: insert between custom_prompt and terminologies
        ds_id = self.ds.id if isinstance(self.ds, CoreDatasource) else None
        extra_prompt_text = self.filter_extra_prompt(session, self.current_user.oid, ds_id)
        if extra_prompt_text:
            self.sql_message.append(HumanPromptMessage(content=extra_prompt_text))
            self.sql_message.append(AIPromptMessage(content='我已确认您提供的额外提示词，我会进行参考。'))

        if _system_templates.get('terminologies'):
            self.sql_message.append(HumanPromptMessage(content=_system_templates['terminologies']))
            self.sql_message.append(AIPromptMessage(content='我已确认您提供的术语信息，我会进行参考。'))
        if _system_templates.get('data_training'):
            self.sql_message.append(HumanPromptMessage(content=_system_templates['data_training']))
            self.sql_message.append(AIPromptMessage(content='我已确认您提供的SQL示例，我会进行参考。'))

        if last_sql_messages is not None and len(last_sql_messages) > 0:
            last_rounds = get_last_conversation_rounds(last_sql_messages, rounds=count_limit)

            for _msg_dict in last_rounds:
                _msg: BaseMessage
                if _msg_dict.get('type') == 'human':
                    _msg = HumanMessage(content=_msg_dict.get('content'))
                    self.sql_message.append(_msg)
                elif _msg_dict.get('type') == 'ai':
                    _msg = AIMessage(content=_msg_dict.get('content'))
                    self.sql_message.append(_msg)

        last_chart_messages: List[dict[str, Any]] = self.generate_chart_logs[-1].messages if len(
            self.generate_chart_logs) > 0 else []
        if self.chat_question.regenerate_record_id:
            # filter record before regenerate_record_id
            _temp_log = next(
                filter(lambda obj: obj.pid == self.chat_question.regenerate_record_id, self.generate_chart_logs), None)
            last_chart_messages: List[dict[str, Any]] = _temp_log.messages if _temp_log else []

        # 排除所有的系统提示词
        last_chart_messages = [obj for obj in last_chart_messages if obj.get("sqlbot_system") != True]

        count_chart_limit = self.base_message_round_count_limit

        self.chart_message = []
        # add sys prompt
        _chart_system_templates = self.chat_question.chart_sys_question()
        self.chart_message.append(SystemPromptMessage(content=_chart_system_templates['system']))
        self.chart_message.append(HumanPromptMessage(content=_chart_system_templates['rules']))
        self.chart_message.append(AIPromptMessage(content='我已掌握所有规则，我会严格遵守这些规则来生成符合要求的JSON。'))
        if last_chart_messages is not None and len(last_chart_messages) > 0:
            last_rounds = get_last_conversation_rounds(last_chart_messages, rounds=count_chart_limit)

            for _msg_dict in last_rounds:
                _msg: BaseMessage
                if _msg_dict.get('type') == 'human':
                    _msg = HumanMessage(content=_msg_dict.get('content'))
                    self.chart_message.append(_msg)
                elif _msg_dict.get('type') == 'ai':
                    _msg = AIMessage(content=_msg_dict.get('content'))
                    self.chart_message.append(_msg)

    def init_record(self, session: Session) -> ChatRecord:
        self.record = save_question(session=session, current_user=self.current_user, question=self.chat_question)
        return self.record

    def get_record(self):
        return self.record

    def set_record(self, record: ChatRecord):
        self.record = record

    def set_articles_number(self, articles_number: int):
        self.articles_number = articles_number

    def get_fields_from_chart(self, _session: Session):
        chart_info = get_chart_config(_session, self.record.id)
        return format_chart_fields(chart_info)

    def filter_terminology_template(self, _session: Session, oid: int = None, ds_id: int = None):
        calculate_oid = oid
        calculate_ds_id = ds_id
        if self.current_assistant:
            calculate_oid = self.current_assistant.oid if self.current_assistant.type != 4 else self.current_user.oid
            if self.current_assistant.type == 1:
                calculate_ds_id = None
        self.current_logs[OperationEnum.FILTER_TERMS] = start_log(session=_session,
                                                                  operate=OperationEnum.FILTER_TERMS,
                                                                  record_id=self.record.id, local_operation=True)

        self.chat_question.terminologies, term_list = get_terminology_template(_session, self.chat_question.question,
                                                                               calculate_oid, calculate_ds_id)
        if settings.METRIC_KIND_TIME_RULES_ENABLED:
            self._metric_kind_context = build_metric_kind_context(term_list)
        else:
            self._metric_kind_context = None
        self.current_logs[OperationEnum.FILTER_TERMS] = end_log(session=_session,
                                                                log=self.current_logs[OperationEnum.FILTER_TERMS],
                                                                full_message=term_list)

    def filter_custom_prompts(self, _session: Session, custom_prompt_type: CustomPromptTypeEnum, oid: int = None,
                              ds_id: int = None):
        if SQLBotLicenseUtil.valid():
            calculate_oid = oid
            calculate_ds_id = ds_id
            if self.current_assistant:
                calculate_oid = self.current_assistant.oid if self.current_assistant.type != 4 else self.current_user.oid
                if self.current_assistant.type == 1:
                    calculate_ds_id = None
            self.current_logs[OperationEnum.FILTER_CUSTOM_PROMPT] = start_log(session=_session,
                                                                              operate=OperationEnum.FILTER_CUSTOM_PROMPT,
                                                                              record_id=self.record.id,
                                                                              local_operation=True)
            self.chat_question.custom_prompt, prompt_list = find_published_custom_prompts(
                _session, custom_prompt_type, calculate_oid, calculate_ds_id
            )
            self.current_logs[OperationEnum.FILTER_CUSTOM_PROMPT] = end_log(session=_session,
                                                                            log=self.current_logs[
                                                                                OperationEnum.FILTER_CUSTOM_PROMPT],
                                                                            full_message=prompt_list)

    def filter_extra_prompt(self, _session: Session, oid: int = None, ds_id: int = None) -> str:
        calculate_oid = oid
        calculate_ds_id = ds_id
        if self.current_assistant:
            calculate_oid = self.current_assistant.oid if self.current_assistant.type != 4 else self.current_user.oid
            if self.current_assistant.type == 1:
                calculate_ds_id = None

        self.current_logs[OperationEnum.FILTER_EXTRA_PROMPT] = start_log(
            session=_session,
            operate=OperationEnum.FILTER_EXTRA_PROMPT,
            record_id=self.record.id,
            local_operation=True,
        )

        prompt_list = []
        prompt_text = ""
        if calculate_ds_id is not None:
            prompt_info = find_enabled_extra_prompt(
                session=_session,
                oid=calculate_oid,
                datasource_id=calculate_ds_id,
                prompt_type=ExtraPromptTypeEnum.GENERATE_SQL.value,
            )
            if prompt_info and prompt_info.prompt:
                prompt_text = prompt_info.prompt
                prompt_list = [{
                    'id': prompt_info.id,
                    'name': prompt_info.description or prompt_info.datasource_name or '',
                    'type': prompt_info.type,
                    'version_id': prompt_info.published_version_id,
                    'version_no': prompt_info.published_version_no,
                    'prompt': prompt_text,
                }]

        self.current_logs[OperationEnum.FILTER_EXTRA_PROMPT] = end_log(
            session=_session,
            log=self.current_logs[OperationEnum.FILTER_EXTRA_PROMPT],
            full_message=prompt_list,
        )
        return prompt_text

    def filter_training_template(self, _session: Session, oid: int = None, ds_id: int = None):
        self.current_logs[OperationEnum.FILTER_SQL_EXAMPLE] = start_log(session=_session,
                                                                        operate=OperationEnum.FILTER_SQL_EXAMPLE,
                                                                        record_id=self.record.id,
                                                                        local_operation=True)
        calculate_oid = oid
        calculate_ds_id = ds_id
        if self.current_assistant:
            calculate_oid = self.current_assistant.oid if self.current_assistant.type != 4 else self.current_user.oid
            if self.current_assistant.type == 1:
                calculate_ds_id = None
        if self.current_assistant and self.current_assistant.type == 1:
            self.chat_question.data_training, example_list = get_training_template(_session,
                                                                                   self.chat_question.question,
                                                                                   calculate_oid,
                                                                                   None, self.current_assistant.id)
        else:
            self.chat_question.data_training, example_list = get_training_template(_session,
                                                                                   self.chat_question.question,
                                                                                   calculate_oid,
                                                                                   calculate_ds_id)
        self.current_logs[OperationEnum.FILTER_SQL_EXAMPLE] = end_log(session=_session,
                                                                      log=self.current_logs[
                                                                          OperationEnum.FILTER_SQL_EXAMPLE],
                                                                      full_message=example_list)

    def choose_table_schema(self, _session: Session):
        self.current_logs[OperationEnum.CHOOSE_TABLE] = start_log(session=_session,
                                                                  operate=OperationEnum.CHOOSE_TABLE,
                                                                  record_id=self.record.id,
                                                                  local_operation=True)
        self.chat_question.db_schema = self.out_ds_instance.get_db_schema(
            self.ds.id, self.chat_question.question) if self.out_ds_instance else get_table_schema(
            session=_session,
            current_user=self.current_user,
            ds=self.ds,
            question=self.chat_question.question)

        self.current_logs[OperationEnum.CHOOSE_TABLE] = end_log(session=_session,
                                                                log=self.current_logs[OperationEnum.CHOOSE_TABLE],
                                                                full_message=self.chat_question.db_schema)

    def generate_analysis(self, _session: Session):
        fields = self.get_fields_from_chart(_session)
        self.chat_question.fields = orjson.dumps(fields).decode()
        data = get_chat_chart_data(_session, self.record.id)
        self.chat_question.data = orjson.dumps(data.get('data')).decode()
        analysis_msg: List[Union[BaseMessage, dict[str, Any]]] = []

        ds_id = self.ds.id if isinstance(self.ds, CoreDatasource) else None

        self.filter_terminology_template(_session, self.current_user.oid, ds_id)

        self.filter_custom_prompts(_session, CustomPromptTypeEnum.ANALYSIS, self.current_user.oid, ds_id)

        analysis_msg.append(SystemPromptMessage(content=self.chat_question.analysis_sys_question()))
        analysis_msg.append(HumanMessage(content=self.chat_question.analysis_user_question()))

        self.current_logs[OperationEnum.ANALYSIS] = start_log(session=_session,
                                                              ai_modal_id=self.chat_question.ai_modal_id,
                                                              ai_modal_name=self.chat_question.ai_modal_name,
                                                              operate=OperationEnum.ANALYSIS,
                                                              record_id=self.record.id,
                                                              full_message=[
                                                                  {'type': msg.type,
                                                                   'sqlbot_system': getattr(msg, 'sqlbot_system',
                                                                                            False) is True,
                                                                   'content': msg.content} for
                                                                  msg
                                                                  in analysis_msg])
        full_thinking_text = ''
        full_analysis_text = ''
        token_usage = {}
        res = process_stream(self.llm.stream(analysis_msg), token_usage)
        for chunk in res:
            if chunk.get('content'):
                full_analysis_text += chunk.get('content')
            if chunk.get('reasoning_content'):
                full_thinking_text += chunk.get('reasoning_content')
            yield chunk

        analysis_msg.append(AIMessage(full_analysis_text))

        self.current_logs[OperationEnum.ANALYSIS] = end_log(session=_session,
                                                            log=self.current_logs[
                                                                OperationEnum.ANALYSIS],
                                                            full_message=[
                                                                {'type': msg.type,
                                                                 'sqlbot_system': getattr(msg, 'sqlbot_system',
                                                                                          False) is True,
                                                                 'content': msg.content}
                                                                for msg in analysis_msg],
                                                            reasoning_content=full_thinking_text,
                                                            token_usage=token_usage)
        self.record = save_analysis_answer(session=_session, record_id=self.record.id,
                                           answer=orjson.dumps({'content': full_analysis_text}).decode())

    def generate_summary(self, _session: Session, result: Optional[dict] = None):
        """Short multi-row insight for BlueCard P1 (main stream, before chart)."""
        payload = result or get_chat_chart_data(_session, self.record.id) or {}
        fields = payload.get('fields') or []
        rows = payload.get('data') or []
        # Cap rows sent to the LLM for latency/cost.
        capped = rows[:50]
        self.chat_question.fields = orjson.dumps(fields).decode()
        self.chat_question.data = orjson.dumps(capped).decode()

        summary_msg: List[Union[BaseMessage, dict[str, Any]]] = [
            SystemPromptMessage(content=self.chat_question.summary_sys_question()),
            HumanMessage(content=self.chat_question.summary_user_question()),
        ]

        self.current_logs[OperationEnum.GENERATE_SUMMARY] = start_log(
            session=_session,
            ai_modal_id=self.chat_question.ai_modal_id,
            ai_modal_name=self.chat_question.ai_modal_name,
            operate=OperationEnum.GENERATE_SUMMARY,
            record_id=self.record.id,
            full_message=[
                {
                    'type': msg.type,
                    'sqlbot_system': getattr(msg, 'sqlbot_system', False) is True,
                    'content': msg.content,
                }
                for msg in summary_msg
            ],
        )

        full_thinking_text = ''
        full_summary_text = ''
        token_usage = {}
        res = process_stream(self.llm.stream(summary_msg), token_usage)
        for chunk in res:
            if chunk.get('content'):
                full_summary_text += chunk.get('content')
            if chunk.get('reasoning_content'):
                full_thinking_text += chunk.get('reasoning_content')
            yield chunk

        summary_msg.append(AIMessage(full_summary_text))
        self.current_logs[OperationEnum.GENERATE_SUMMARY] = end_log(
            session=_session,
            log=self.current_logs[OperationEnum.GENERATE_SUMMARY],
            full_message=[
                {
                    'type': msg.type,
                    'sqlbot_system': getattr(msg, 'sqlbot_system', False) is True,
                    'content': msg.content,
                }
                for msg in summary_msg
            ],
            reasoning_content=full_thinking_text,
            token_usage=token_usage,
        )
        self.record = save_summary_answer(
            session=_session,
            record_id=self.record.id,
            answer=full_summary_text,
        )

    def generate_field_aliases(self, _session: Session, fields: Optional[list] = None) -> list:
        """
        BlueCard field labels: terminology/static dict first, LLM bilingual fallback.
        Always returns a list of {field, name_zh, name_en, source}.
        """
        field_list = [f for f in (fields or []) if f]
        if not field_list:
            return []

        from apps.chat.bluecard.field_aliases import alias_entry, humanize_en_field

        oid = getattr(self.current_user, 'oid', None) or 1
        ds_id = self.ds.id if isinstance(self.ds, CoreDatasource) else None
        dict_aliases = resolve_dict_aliases(_session, field_list, oid=oid, datasource=ds_id)
        missing = incomplete_fields(field_list, dict_aliases)

        llm_aliases: dict = {}
        if missing:
            try:
                fields_json = orjson.dumps(missing).decode()
                alias_msg: List[Union[BaseMessage, dict[str, Any]]] = [
                    SystemPromptMessage(content=self.chat_question.field_alias_sys_question()),
                    HumanMessage(content=self.chat_question.field_alias_user_question(fields_json)),
                ]
                self.current_logs[OperationEnum.GENERATE_FIELD_ALIASES] = start_log(
                    session=_session,
                    ai_modal_id=self.chat_question.ai_modal_id,
                    ai_modal_name=self.chat_question.ai_modal_name,
                    operate=OperationEnum.GENERATE_FIELD_ALIASES,
                    record_id=self.record.id,
                    full_message=[
                        {
                            'type': msg.type,
                            'sqlbot_system': getattr(msg, 'sqlbot_system', False) is True,
                            'content': msg.content,
                        }
                        for msg in alias_msg
                    ],
                )
                full_text = ''
                token_usage = {}
                res = process_stream(self.llm.stream(alias_msg), token_usage)
                for chunk in res:
                    if chunk.get('content'):
                        full_text += chunk.get('content')
                llm_aliases = parse_llm_alias_payload(full_text)
                llm_aliases = {k: v for k, v in llm_aliases.items() if k in set(missing)}
                alias_msg.append(AIMessage(full_text))
                self.current_logs[OperationEnum.GENERATE_FIELD_ALIASES] = end_log(
                    session=_session,
                    log=self.current_logs[OperationEnum.GENERATE_FIELD_ALIASES],
                    full_message=[
                        {
                            'type': msg.type,
                            'sqlbot_system': getattr(msg, 'sqlbot_system', False) is True,
                            'content': msg.content,
                        }
                        for msg in alias_msg
                    ],
                    token_usage=token_usage,
                )
            except Exception as err:
                SQLBotLogUtil.warning(
                    f'bluecard field_aliases llm failed record={self.record.id} err={err}'
                )

        merged = merge_aliases(dict_aliases, llm_aliases)
        for f in field_list:
            if f not in merged:
                merged[f] = alias_entry(
                    f,
                    name_zh=humanize_en_field(f),
                    name_en=humanize_en_field(f),
                    source='fallback',
                )
        result = aliases_list(merged, field_list)
        self.record = save_field_aliases(session=_session, record_id=self.record.id, aliases=result)
        return result

    def generate_predict(self, _session: Session):
        fields = self.get_fields_from_chart(_session)
        self.chat_question.fields = orjson.dumps(fields).decode()
        data = get_chat_chart_data(_session, self.record.id)
        self.chat_question.data = orjson.dumps(data.get('data')).decode()

        ds_id = self.ds.id if isinstance(self.ds, CoreDatasource) else None
        self.filter_custom_prompts(_session, CustomPromptTypeEnum.PREDICT_DATA, self.current_user.oid, ds_id)

        predict_msg: List[Union[BaseMessage, dict[str, Any]]] = []
        predict_msg.append(SystemPromptMessage(content=self.chat_question.predict_sys_question()))
        predict_msg.append(HumanMessage(content=self.chat_question.predict_user_question()))

        self.current_logs[OperationEnum.PREDICT_DATA] = start_log(session=_session,
                                                                  ai_modal_id=self.chat_question.ai_modal_id,
                                                                  ai_modal_name=self.chat_question.ai_modal_name,
                                                                  operate=OperationEnum.PREDICT_DATA,
                                                                  record_id=self.record.id,
                                                                  full_message=[
                                                                      {'type': msg.type,
                                                                       'sqlbot_system': getattr(msg, 'sqlbot_system',
                                                                                                False) is True,
                                                                       'content': msg.content} for
                                                                      msg
                                                                      in predict_msg])
        full_thinking_text = ''
        full_predict_text = ''
        token_usage = {}
        res = process_stream(self.llm.stream(predict_msg), token_usage)
        for chunk in res:
            if chunk.get('content'):
                full_predict_text += chunk.get('content')
            if chunk.get('reasoning_content'):
                full_thinking_text += chunk.get('reasoning_content')
            yield chunk

        predict_msg.append(AIMessage(full_predict_text))
        self.record = save_predict_answer(session=_session, record_id=self.record.id,
                                          answer=orjson.dumps({'content': full_predict_text}).decode())
        self.current_logs[OperationEnum.PREDICT_DATA] = end_log(session=_session,
                                                                log=self.current_logs[
                                                                    OperationEnum.PREDICT_DATA],
                                                                full_message=[
                                                                    {'type': msg.type,
                                                                     'sqlbot_system': getattr(msg, 'sqlbot_system',
                                                                                              False) is True,
                                                                     'content': msg.content}
                                                                    for msg in predict_msg],
                                                                reasoning_content=full_thinking_text,
                                                                token_usage=token_usage)

    def generate_recommend_questions_task(self, _session: Session):

        # get schema
        if self.ds and not self.chat_question.db_schema:
            self.chat_question.db_schema = self.out_ds_instance.get_db_schema(
                self.ds.id, self.chat_question.question) if self.out_ds_instance else get_table_schema(
                session=_session,
                current_user=self.current_user, ds=self.ds,
                question=self.chat_question.question,
                embedding=False)

        guess_msg: List[Union[BaseMessage, dict[str, Any]]] = []
        guess_msg.append(SystemPromptMessage(content=self.chat_question.guess_sys_question(self.articles_number)))

        old_questions = list(map(lambda q: q.strip(), get_old_questions(_session, self.record.datasource)))
        guess_msg.append(
            HumanMessage(content=self.chat_question.guess_user_question(orjson.dumps(old_questions).decode())))

        self.current_logs[OperationEnum.GENERATE_RECOMMENDED_QUESTIONS] = start_log(session=_session,
                                                                                    ai_modal_id=self.chat_question.ai_modal_id,
                                                                                    ai_modal_name=self.chat_question.ai_modal_name,
                                                                                    operate=OperationEnum.GENERATE_RECOMMENDED_QUESTIONS,
                                                                                    record_id=self.record.id,
                                                                                    full_message=[
                                                                                        {'type': msg.type,
                                                                                         'sqlbot_system': getattr(msg,
                                                                                                                  'sqlbot_system',
                                                                                                                  False) is True,
                                                                                         'content': msg.content} for
                                                                                        msg
                                                                                        in guess_msg])
        full_thinking_text = ''
        full_guess_text = ''
        token_usage = {}
        res = process_stream(self.llm.stream(guess_msg), token_usage)
        for chunk in res:
            if chunk.get('content'):
                full_guess_text += chunk.get('content')
            if chunk.get('reasoning_content'):
                full_thinking_text += chunk.get('reasoning_content')
            yield chunk

        guess_msg.append(AIMessage(full_guess_text))

        self.current_logs[OperationEnum.GENERATE_RECOMMENDED_QUESTIONS] = end_log(session=_session,
                                                                                  log=self.current_logs[
                                                                                      OperationEnum.GENERATE_RECOMMENDED_QUESTIONS],
                                                                                  full_message=[
                                                                                      {'type': msg.type,
                                                                                       'sqlbot_system': getattr(msg,
                                                                                                                'sqlbot_system',
                                                                                                                False) is True,
                                                                                       'content': msg.content}
                                                                                      for msg in guess_msg],
                                                                                  reasoning_content=full_thinking_text,
                                                                                  token_usage=token_usage)
        self.record = save_recommend_question_answer(session=_session, record_id=self.record.id,
                                                     answer={'content': full_guess_text},
                                                     articles_number=self.articles_number)

        yield {'recommended_question': self.record.recommended_question}

    def select_datasource(self, _session: Session):
        datasource_msg: List[Union[BaseMessage, dict[str, Any]]] = []
        datasource_msg.append(SystemPromptMessage(self.chat_question.datasource_sys_question()))
        if self.current_assistant and self.current_assistant.type != 4:
            _ds_list = get_assistant_ds(session=_session, llm_service=self)
        else:
            stmt = select(CoreDatasource.id, CoreDatasource.name, CoreDatasource.description).where(
                and_(CoreDatasource.oid == self.current_user.oid))
            _ds_list = [
                {
                    "id": ds.id,
                    "name": ds.name,
                    "description": ds.description
                }
                for ds in _session.exec(stmt)
            ]
        if not _ds_list:
            raise SingleMessageError('No available datasource configuration found')
        ignore_auto_select = _ds_list and len(_ds_list) == 1
        # ignore auto select ds

        full_thinking_text = ''
        full_text = ''
        if not ignore_auto_select:
            if settings.TABLE_EMBEDDING_ENABLED and (
                    not self.current_assistant or (self.current_assistant and self.current_assistant.type != 1)):
                _ds_list = get_ds_embedding(_session, self.current_user, _ds_list, self.out_ds_instance,
                                            self.chat_question.question, self.current_assistant)
                # yield {'content': '{"id":' + str(ds.get('id')) + '}'}

            _ds_list_dict = []
            for _ds in _ds_list:
                _ds_list_dict.append(_ds)
            datasource_msg.append(
                HumanMessage(self.chat_question.datasource_user_question(orjson.dumps(_ds_list_dict).decode())))

            self.current_logs[OperationEnum.CHOOSE_DATASOURCE] = start_log(session=_session,
                                                                           ai_modal_id=self.chat_question.ai_modal_id,
                                                                           ai_modal_name=self.chat_question.ai_modal_name,
                                                                           operate=OperationEnum.CHOOSE_DATASOURCE,
                                                                           record_id=self.record.id,
                                                                           full_message=[{'type': msg.type,
                                                                                          'sqlbot_system': getattr(msg,
                                                                                                                   'sqlbot_system',
                                                                                                                   False) is True,
                                                                                          'content': msg.content}
                                                                                         for
                                                                                         msg in datasource_msg])

            token_usage = {}
            res = process_stream(self.llm.stream(datasource_msg), token_usage)
            for chunk in res:
                if chunk.get('content'):
                    full_text += chunk.get('content')
                if chunk.get('reasoning_content'):
                    full_thinking_text += chunk.get('reasoning_content')
                yield chunk
            datasource_msg.append(AIMessage(full_text))

            self.current_logs[OperationEnum.CHOOSE_DATASOURCE] = end_log(session=_session,
                                                                         log=self.current_logs[
                                                                             OperationEnum.CHOOSE_DATASOURCE],
                                                                         full_message=[
                                                                             {'type': msg.type,
                                                                              'sqlbot_system': getattr(msg,
                                                                                                       'sqlbot_system',
                                                                                                       False) is True,
                                                                              'content': msg.content}
                                                                             for msg in datasource_msg],
                                                                         reasoning_content=full_thinking_text,
                                                                         token_usage=token_usage)

            json_str = extract_nested_json(full_text)
            if json_str is None:
                raise SingleMessageError(f'Cannot parse datasource from answer: {full_text}')
            ds = orjson.loads(json_str)

        _error: Exception | None = None
        _datasource: int | None = None
        _engine_type: str | None = None
        try:
            data: dict = _ds_list[0] if ignore_auto_select else ds

            if data.get('id') and data.get('id') != 0:
                _datasource = data['id']
                _chat = _session.get(Chat, self.record.chat_id)
                _chat.datasource = _datasource
                if self.current_assistant and self.current_assistant.type in dynamic_ds_types:
                    _ds = self.out_ds_instance.get_ds(data['id'])
                    self.ds = _ds
                    self.chat_question.engine = _ds.type + get_version(self.ds)

                    _engine_type = self.chat_question.engine
                    _chat.engine_type = _ds.type
                else:
                    _ds = _session.get(CoreDatasource, _datasource)
                    if not _ds:
                        _datasource = None
                        raise SingleMessageError(f"Datasource configuration with id {_datasource} not found")
                    self.ds = CoreDatasource(**_ds.model_dump())
                    self.chat_question.engine = (_ds.type_name if _ds.type != 'excel' else 'PostgreSQL') + get_version(
                        self.ds)

                    _engine_type = self.chat_question.engine
                    _chat.engine_type = _ds.type_name
                # save chat
                with _session.begin_nested():
                    # 为了能继续记日志，先单独处理下事务
                    try:
                        _session.add(_chat)
                        _session.flush()
                        _session.refresh(_chat)
                        _session.commit()
                    except Exception as e:
                        _session.rollback()
                        raise e

            elif data['fail']:
                raise SingleMessageError(data['fail'])
            else:
                raise SingleMessageError('No available datasource configuration found')

        except Exception as e:
            _error = e

        if not ignore_auto_select and not settings.TABLE_EMBEDDING_ENABLED:
            self.record = save_select_datasource_answer(session=_session, record_id=self.record.id,
                                                        answer=orjson.dumps({'content': full_text}).decode(),
                                                        datasource=_datasource,
                                                        engine_type=_engine_type)
        if self.ds:
            oid = self.ds.oid if isinstance(self.ds, CoreDatasource) else 1
            ds_id = self.ds.id if isinstance(self.ds, CoreDatasource) else None

            self.filter_terminology_template(_session, oid, ds_id)

            self.filter_training_template(_session, oid, ds_id)

            self.filter_custom_prompts(_session, CustomPromptTypeEnum.GENERATE_SQL, oid, ds_id)

            self.init_messages(_session)

        if _error:
            raise _error

    def _get_schema_text(self) -> str:
        schema = self.chat_question.db_schema or ''
        if not schema and self.sql_message:
            for msg in self.sql_message:
                content = getattr(msg, 'content', '') or ''
                if '<m-schema>' in content or '【Schema】' in content:
                    schema = content
                    break
        return schema

    def _append_clarification_context_to_sql_messages(self, earliest_date: Optional[str] = None):
        clarification = self.record.clarification if isinstance(self.record.clarification, dict) else None
        if not clarification:
            return
        ed = earliest_date or get_query_earliest_date(None)
        resolved_xml = resolved_blocks_xml(clarification, earliest_date=ed)
        if resolved_xml:
            self.sql_message.append(HumanMessage(content=resolved_xml))
            self.sql_message.append(AIMessage(content='我已记录用户确认的字段映射与时间范围，将严格遵守。'))
        if self._force_clarification_finalize or should_force_finalize(clarification):
            self.sql_message.append(HumanMessage(content=clarification_limit_xml(clarification)))
            self.sql_message.append(AIMessage(content='已达澄清上限，我将根据已确认信息生成 SQL，不再请求澄清。'))

    def _append_inferred_question_time_to_sql_messages(self, earliest_date: Optional[str] = None):
        """When question already states a relative range (e.g. 本年度), inject concrete dates."""
        clarification = self.record.clarification if isinstance(self.record.clarification, dict) else {}
        if get_time_range_resolved(clarification):
            return
        question = (self.chat_question.question or '').strip()
        if not question:
            return
        ed = earliest_date or get_query_earliest_date(None)
        inferred = infer_time_range_from_question(
            question, ed, lang=self.chat_question.lang,
        )
        if not inferred:
            return
        self._inferred_time_range = inferred
        self.sql_message.append(HumanMessage(content=question_time_range_xml(inferred)))
        self.sql_message.append(AIMessage(content='我将按问题中的时间范围生成带时间过滤的 SQL。'))
        SQLBotLogUtil.info(
            f'inferred question time range record={self.record.id} '
            f'field={inferred.get("field")} '
            f'{inferred.get("date_start")}..{inferred.get("date_end")}'
        )

    def _check_schema_id_prefilter(self) -> Optional[dict]:
        if not settings.CLARIFICATION_SCHEMA_PREFILTER_ENABLED:
            return None
        if self._force_clarification_finalize:
            return None
        clarification = self.record.clarification if isinstance(self.record.clarification, dict) else {}
        if clarification.get('current'):
            return None
        question = self.chat_question.question or ''
        resolved_values = {
            str(r.get('raw_value'))
            for r in (clarification.get('resolved') or [])
            if r.get('raw_value') is not None
        }
        q_ids = extract_numeric_ids(question)
        if q_ids and resolved_values and all(i in resolved_values for i in q_ids):
            return None
        schema = self._get_schema_text()
        result = detect_id_clarification_needed(question, schema, resolved_values)
        id_fields = parse_id_fields_from_schema(schema)
        numeric_ids = extract_numeric_ids(question)
        if result:
            SQLBotLogUtil.info(
                f'clarification schema prefilter triggered record={self.record.id} '
                f'ids={numeric_ids} id_fields={[f["field"] for f in id_fields]}'
            )
        elif numeric_ids and len(id_fields) >= 2:
            SQLBotLogUtil.info(
                f'clarification schema prefilter skipped record={self.record.id} '
                f'ids={numeric_ids} id_fields={[f["field"] for f in id_fields]}'
            )
        return result

    def _check_time_range_prefilter_global(
        self, session: Session, question: str, clarification: dict,
    ) -> Optional[dict]:
        if question_has_time_constraint(question, clarification.get('resolved')):
            return None
        earliest = get_query_earliest_date(session)
        SQLBotLogUtil.info(
            f'clarification time prefilter triggered record={self.record.id} earliest={earliest}'
        )
        return build_time_range_clarification(earliest, lang=self.chat_question.lang)

    def _check_time_range_prefilter_by_metric_kind(
        self, session: Session, ctx: MetricKindContext, question: str, clarification: dict,
    ) -> Optional[dict]:
        resolved = clarification.get('resolved')

        if ctx.scenario == SCENARIO_BALANCE_ONLY:
            balance_time = classify_balance_time(question)
            if balance_time.error_message:
                raise SingleMessageError(orjson.dumps({
                    'message': balance_time.error_message,
                }).decode())
            if balance_time.llm_hint:
                self._balance_time_llm_hint = balance_time.llm_hint
            SQLBotLogUtil.info(
                f'metric_kind balance-only skip time prefilter record={self.record.id} '
                f'balance_time={balance_time.kind.value}'
            )
            return None

        has_time = question_has_explicit_time_constraint(question, resolved)

        if ctx.scenario == SCENARIO_FLOW_ONLY:
            if has_time:
                return None
            earliest = get_query_earliest_date(session)
            SQLBotLogUtil.info(
                f'metric_kind flow-only time prefilter record={self.record.id} earliest={earliest}'
            )
            return build_time_range_clarification(earliest, lang=self.chat_question.lang)

        if ctx.scenario == SCENARIO_MIXED:
            if has_time:
                self._needs_mixed_metric_hint = True
                SQLBotLogUtil.info(
                    f'metric_kind mixed with explicit time record={self.record.id}'
                )
                return None
            earliest = get_query_earliest_date(session)
            SQLBotLogUtil.info(
                f'metric_kind mixed time prefilter (flow only) record={self.record.id} earliest={earliest}'
            )
            self._needs_mixed_metric_hint = True
            return build_time_range_clarification(earliest, lang=self.chat_question.lang)

        return self._check_time_range_prefilter_global(session, question, clarification)

    def _append_metric_kind_hints_to_sql_messages(self):
        hints: list[str] = []
        if self._balance_time_llm_hint:
            hints.append(
                f'<balance-time-hint>\n{self._balance_time_llm_hint}\n</balance-time-hint>'
            )
        if self._needs_mixed_metric_hint:
            hints.append(MIXED_METRIC_KIND_HINT)
        if not hints:
            return
        content = '\n'.join(hints)
        self.sql_message.append(HumanMessage(content=content))
        self.sql_message.append(AIMessage(content='我已了解本次指标语义与时间处理要求。'))

    def _check_time_range_prefilter(self, session: Session) -> Optional[dict]:
        if not settings.TIME_RANGE_CLARIFICATION_ENABLED:
            return None
        if self._force_clarification_finalize:
            return None
        clarification = self.record.clarification if isinstance(self.record.clarification, dict) else {}
        if clarification.get('current'):
            return None
        question = self.chat_question.question or ''

        if settings.METRIC_KIND_TIME_RULES_ENABLED and self._metric_kind_context:
            ctx = self._metric_kind_context
            if ctx.scenario != SCENARIO_NONE:
                return self._check_time_range_prefilter_by_metric_kind(
                    session, ctx, question, clarification,
                )

        return self._check_time_range_prefilter_global(session, question, clarification)

    def generate_sql(self, _session: Session, skip_prefilter: bool = False):
        earliest = get_query_earliest_date(_session)
        if not skip_prefilter:
            self._append_clarification_context_to_sql_messages(earliest_date=earliest)
            time_prefilter = self._check_time_range_prefilter(_session)
            if time_prefilter:
                raise ClarificationRequiredError(time_prefilter)
            prefilter = self._check_schema_id_prefilter()
            if prefilter:
                raise ClarificationRequiredError(prefilter)
            self._append_inferred_question_time_to_sql_messages(earliest_date=earliest)
            self._append_metric_kind_hints_to_sql_messages()
        # append current question
        if not skip_prefilter:
            self.sql_message.append(HumanMessage(
                self.chat_question.sql_user_question(current_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                                     change_title=self.change_title)))

        self.current_logs[OperationEnum.GENERATE_SQL] = start_log(session=_session,
                                                                  ai_modal_id=self.chat_question.ai_modal_id,
                                                                  ai_modal_name=self.chat_question.ai_modal_name,
                                                                  operate=OperationEnum.GENERATE_SQL,
                                                                  record_id=self.record.id,
                                                                  full_message=[
                                                                      {'type': msg.type,
                                                                       'sqlbot_system': getattr(msg, 'sqlbot_system',
                                                                                                False) is True,
                                                                       'content': msg.content} for msg
                                                                      in self.sql_message])
        full_thinking_text = ''
        full_sql_text = ''
        token_usage = {}
        res = process_stream(self.llm.stream(self.sql_message), token_usage)
        for chunk in res:
            if chunk.get('content'):
                full_sql_text += chunk.get('content')
            if chunk.get('reasoning_content'):
                full_thinking_text += chunk.get('reasoning_content')
            yield chunk

        self.sql_message.append(AIMessage(full_sql_text))

        self.current_logs[OperationEnum.GENERATE_SQL] = end_log(session=_session,
                                                                log=self.current_logs[OperationEnum.GENERATE_SQL],
                                                                full_message=[{'type': msg.type,
                                                                               'sqlbot_system': getattr(msg,
                                                                                                        'sqlbot_system',
                                                                                                        False) is True,
                                                                               'content': msg.content}
                                                                              for msg in self.sql_message],
                                                                reasoning_content=full_thinking_text,
                                                                token_usage=token_usage)
        self.record = save_sql_answer(session=_session, record_id=self.record.id,
                                      answer=orjson.dumps({'content': full_sql_text}).decode())

    def generate_with_sub_sql(self, session: Session, sql, sub_mappings: list):
        sub_query = json.dumps(sub_mappings, ensure_ascii=False)
        self.chat_question.sql = sql
        self.chat_question.sub_query = sub_query
        dynamic_sql_msg: List[Union[BaseMessage, dict[str, Any]]] = []
        dynamic_sql_msg.append(SystemPromptMessage(content=self.chat_question.dynamic_sys_question()))
        dynamic_sql_msg.append(HumanMessage(content=self.chat_question.dynamic_user_question()))

        self.current_logs[OperationEnum.GENERATE_DYNAMIC_SQL] = start_log(session=session,
                                                                          ai_modal_id=self.chat_question.ai_modal_id,
                                                                          ai_modal_name=self.chat_question.ai_modal_name,
                                                                          operate=OperationEnum.GENERATE_DYNAMIC_SQL,
                                                                          record_id=self.record.id,
                                                                          full_message=[{'type': msg.type,
                                                                                         'sqlbot_system': getattr(msg,
                                                                                                                  'sqlbot_system',
                                                                                                                  False) is True,
                                                                                         'content': msg.content}
                                                                                        for
                                                                                        msg in dynamic_sql_msg])

        full_thinking_text = ''
        full_dynamic_text = ''
        token_usage = {}
        res = process_stream(self.llm.stream(dynamic_sql_msg), token_usage)
        for chunk in res:
            if chunk.get('content'):
                full_dynamic_text += chunk.get('content')
            if chunk.get('reasoning_content'):
                full_thinking_text += chunk.get('reasoning_content')

        dynamic_sql_msg.append(AIMessage(full_dynamic_text))

        self.current_logs[OperationEnum.GENERATE_DYNAMIC_SQL] = end_log(session=session,
                                                                        log=self.current_logs[
                                                                            OperationEnum.GENERATE_DYNAMIC_SQL],
                                                                        full_message=[
                                                                            {'type': msg.type,
                                                                             'sqlbot_system': getattr(msg,
                                                                                                      'sqlbot_system',
                                                                                                      False) is True,
                                                                             'content': msg.content}
                                                                            for msg in dynamic_sql_msg],
                                                                        reasoning_content=full_thinking_text,
                                                                        token_usage=token_usage)

        SQLBotLogUtil.info(full_dynamic_text)
        return full_dynamic_text

    def generate_assistant_dynamic_sql(self, _session: Session, sql, tables: List):
        ds: AssistantOutDsSchema = self.ds
        sub_query = []
        result_dict = {}
        for table in ds.tables:
            if table.name in tables and table.sql:
                # sub_query.append({"table": table.name, "query": table.sql})
                result_dict[table.name] = table.sql
                sub_query.append({"table": table.name, "query": f'{dynamic_subsql_prefix}{table.name}'})
        if not sub_query:
            return None
        temp_sql_text = self.generate_with_sub_sql(session=_session, sql=sql, sub_mappings=sub_query)
        result_dict['sqlbot_temp_sql_text'] = temp_sql_text
        return result_dict

    def build_table_filter(self, session: Session, sql: str, filters: list):
        filter = json.dumps(filters, ensure_ascii=False)
        self.chat_question.sql = sql
        self.chat_question.filter = filter
        permission_sql_msg: List[Union[BaseMessage, dict[str, Any]]] = []
        permission_sql_msg.append(SystemPromptMessage(content=self.chat_question.filter_sys_question()))
        permission_sql_msg.append(HumanMessage(content=self.chat_question.filter_user_question()))

        self.current_logs[OperationEnum.GENERATE_SQL_WITH_PERMISSIONS] = start_log(session=session,
                                                                                   ai_modal_id=self.chat_question.ai_modal_id,
                                                                                   ai_modal_name=self.chat_question.ai_modal_name,
                                                                                   operate=OperationEnum.GENERATE_SQL_WITH_PERMISSIONS,
                                                                                   record_id=self.record.id,
                                                                                   full_message=[
                                                                                       {'type': msg.type,
                                                                                        'sqlbot_system': getattr(msg,
                                                                                                                 'sqlbot_system',
                                                                                                                 False) is True,
                                                                                        'content': msg.content} for
                                                                                       msg
                                                                                       in permission_sql_msg])
        full_thinking_text = ''
        full_filter_text = ''
        token_usage = {}
        res = process_stream(self.llm.stream(permission_sql_msg), token_usage)
        for chunk in res:
            if chunk.get('content'):
                full_filter_text += chunk.get('content')
            if chunk.get('reasoning_content'):
                full_thinking_text += chunk.get('reasoning_content')

        permission_sql_msg.append(AIMessage(full_filter_text))

        self.current_logs[OperationEnum.GENERATE_SQL_WITH_PERMISSIONS] = end_log(session=session,
                                                                                 log=self.current_logs[
                                                                                     OperationEnum.GENERATE_SQL_WITH_PERMISSIONS],
                                                                                 full_message=[
                                                                                     {'type': msg.type,
                                                                                      'sqlbot_system': getattr(msg,
                                                                                                               'sqlbot_system',
                                                                                                               False) is True,
                                                                                      'content': msg.content}
                                                                                     for msg in permission_sql_msg],
                                                                                 reasoning_content=full_thinking_text,
                                                                                 token_usage=token_usage)

        SQLBotLogUtil.info(full_filter_text)
        return full_filter_text

    def generate_filter(self, _session: Session, sql: str, tables: List):
        filters = get_row_permission_filters(session=_session, current_user=self.current_user, ds=self.ds,
                                             tables=tables)
        if not filters:
            return None
        return self.build_table_filter(session=_session, sql=sql, filters=filters)

    def generate_assistant_filter(self, _session: Session, sql, tables: List):
        ds: AssistantOutDsSchema = self.ds
        filters = []
        for table in ds.tables:
            if table.name in tables and table.rule:
                filters.append({"table": table.name, "filter": table.rule})
        if not filters:
            return None
        return self.build_table_filter(session=_session, sql=sql, filters=filters)

    def generate_chart(self, _session: Session, chart_type: Optional[str] = '', schema: Optional[str] = ''):
        # append current question
        self.chart_message.append(HumanMessage(self.chat_question.chart_user_question(chart_type, schema)))

        self.current_logs[OperationEnum.GENERATE_CHART] = start_log(session=_session,
                                                                    ai_modal_id=self.chat_question.ai_modal_id,
                                                                    ai_modal_name=self.chat_question.ai_modal_name,
                                                                    operate=OperationEnum.GENERATE_CHART,
                                                                    record_id=self.record.id,
                                                                    full_message=[
                                                                        {'type': msg.type,
                                                                         'sqlbot_system': getattr(msg, 'sqlbot_system',
                                                                                                  False) is True,
                                                                         'content': msg.content} for
                                                                        msg
                                                                        in self.chart_message])
        full_thinking_text = ''
        full_chart_text = ''
        token_usage = {}
        res = process_stream(self.llm.stream(self.chart_message), token_usage)
        for chunk in res:
            if chunk.get('content'):
                full_chart_text += chunk.get('content')
            if chunk.get('reasoning_content'):
                full_thinking_text += chunk.get('reasoning_content')
            yield chunk

        self.chart_message.append(AIMessage(full_chart_text))

        self.record = save_chart_answer(session=_session, record_id=self.record.id,
                                        answer=orjson.dumps({'content': full_chart_text}).decode())
        self.current_logs[OperationEnum.GENERATE_CHART] = end_log(session=_session,
                                                                  log=self.current_logs[OperationEnum.GENERATE_CHART],
                                                                  full_message=[
                                                                      {'type': msg.type,
                                                                       'sqlbot_system': getattr(msg, 'sqlbot_system',
                                                                                                False) is True,
                                                                       'content': msg.content}
                                                                      for msg in self.chart_message],
                                                                  reasoning_content=full_thinking_text,
                                                                  token_usage=token_usage)

    def check_sql(self, session: Session, res: str, operate: OperationEnum) -> tuple[str, Optional[list]]:
        json_str = extract_nested_json(res)

        log = self.current_logs[operate]

        if json_str is None:
            trigger_log_error(session, log)
            raise SingleMessageError(orjson.dumps({'message': 'SQL answer is not a valid json object',
                                                   'traceback': "SQL answer is not a valid json object:\n" + res}).decode())
        sql: str
        data: dict
        try:
            data = orjson.loads(json_str)

            if data['success']:
                sql = data['sql']
            elif data.get('clarification'):
                if self._force_clarification_finalize:
                    raise SingleMessageError(orjson.dumps({
                        'message': '已达澄清上限，但模型仍未返回 SQL，请简化问题后重试',
                    }).decode())
                raise ClarificationRequiredError(data['clarification'])
            else:
                message = data.get('message') or 'Unknown error'
                raise SingleMessageError(message)
        except ClarificationRequiredError:
            raise
        except SingleMessageError as e:
            trigger_log_error(session, log)
            raise e
        except Exception:
            trigger_log_error(session, log)
            raise SingleMessageError(orjson.dumps({'message': 'Cannot parse sql from answer',
                                                   'traceback': "Cannot parse sql from answer:\n" + res}).decode())

        if sql.strip() == '':
            trigger_log_error(session, log)
            raise SingleMessageError("SQL query is empty")
        return sql, data.get('tables')

    @staticmethod
    def get_chart_type_from_sql_answer(res: str) -> Optional[str]:
        json_str = extract_nested_json(res)
        if json_str is None:
            return None

        chart_type: Optional[str]
        data: dict
        try:
            data = orjson.loads(json_str)

            if data['success']:
                chart_type = data['chart-type']
            else:
                return None
        except Exception:
            return None

        return chart_type

    @staticmethod
    def get_brief_from_sql_answer(res: str) -> Optional[str]:
        json_str = extract_nested_json(res)
        if json_str is None:
            return None

        brief: Optional[str]
        data: dict
        try:
            data = orjson.loads(json_str)

            if data['success']:
                brief = data['brief']
            else:
                return None
        except Exception:
            return None

        return brief

    def check_save_sql(self, session: Session, res: str, operate: OperationEnum) -> str:
        sql, *_ = self.check_sql(session=session, res=res, operate=operate)
        save_sql(session=session, sql=sql, record_id=self.record.id)

        self.chat_question.sql = sql

        return sql

    def check_save_chart(self, session: Session, res: str) -> Dict[str, Any]:

        json_str = extract_nested_json(res)
        if json_str is None:
            raise SingleMessageError(orjson.dumps({'message': 'Cannot parse chart config from answer',
                                                   'traceback': "Cannot parse chart config from answer:\n" + res}).decode())
        data: dict

        chart: Dict[str, Any] = {}
        message = ''
        error = False

        try:
            data = orjson.loads(json_str)
            if data['type'] and data['type'] != 'error':
                # todo type check
                chart = data
                if chart.get('columns'):
                    for v in chart.get('columns'):
                        v['value'] = v.get('value').lower()
                if chart.get('axis'):
                    if chart.get('axis').get('x'):
                        chart.get('axis').get('x')['value'] = chart.get('axis').get('x').get('value').lower()
                    y_axis = chart.get('axis').get('y')
                    if y_axis:
                        if isinstance(y_axis, list):
                            # 数组格式: y: [{name, value}, ...]
                            for item in y_axis:
                                if item.get('value'):
                                    item['value'] = item['value'].lower()
                        elif isinstance(y_axis, dict) and y_axis.get('value'):
                            # 旧格式: y: {name, value}
                            y_axis['value'] = y_axis['value'].lower()
                    if chart.get('axis').get('series'):
                        chart.get('axis').get('series')['value'] = chart.get('axis').get('series').get('value').lower()
                if chart.get('axis') and chart['axis'].get('multi-quota'):
                    multi_quota = chart['axis']['multi-quota']
                    if multi_quota.get('value'):
                        if isinstance(multi_quota['value'], list):
                            # 将数组中的每个值转换为小写
                            multi_quota['value'] = [v.lower() if v else v for v in multi_quota['value']]
                        elif isinstance(multi_quota['value'], str):
                            # 如果是字符串，也转换为小写
                            multi_quota['value'] = multi_quota['value'].lower()
            elif data['type'] == 'error':
                message = data['reason']
                error = True
            else:
                raise Exception('Chart is empty')
        except Exception:
            error = True
            message = orjson.dumps({'message': 'Cannot parse chart config from answer',
                                    'traceback': "Cannot parse chart config from answer:\n" + res}).decode()

        if error:
            raise SingleMessageError(message)

        save_chart(session=session, chart=orjson.dumps(chart).decode(), record_id=self.record.id)

        return chart

    def check_save_predict_data(self, session: Session, res: str) -> bool:

        json_str = extract_nested_json(res)

        if not json_str:
            json_str = ''

        save_predict_data(session=session, record_id=self.record.id, data=json_str)

        if json_str == '':
            return False

        return True

    def save_error(self, session: Session, message: str):
        return save_error_message(session=session, record_id=self.record.id, message=message)

    def save_sql_data(self, session: Session, data_obj: Dict[str, Any]):
        try:
            data_result = data_obj.get('data')
            limit = 1000
            if data_result:
                data_result = prepare_for_orjson(data_result)
                if data_result and len(data_result) > limit and self.enable_sql_row_limit:
                    data_obj['data'] = data_result[:limit]
                    data_obj['limit'] = limit
                else:
                    data_obj['data'] = data_result
                data_obj['datasource'] = self.ds.id
            return save_sql_exec_data(session=session, record_id=self.record.id,
                                      data=orjson.dumps(data_obj).decode())
        except Exception as e:
            raise e

    def finish(self, session: Session):
        record = get_chat_record_by_id(session, self.record.id)
        if is_clarification_pending(record):
            return record
        return finish_record(session=session, record_id=self.record.id)

    def _build_clarification_state(self, raw_clarification: dict) -> dict:
        current = normalize_current(raw_clarification)
        existing = self.record.clarification if isinstance(self.record.clarification, dict) else None
        if existing and (existing.get('resolved') or existing.get('ask_count')):
            clarification = {**existing, 'current': current}
            if is_time_factor(raw_clarification) or is_time_factor(current):
                return clarification
            return increment_ask_count(clarification)
        return build_initial_clarification(current, self.clarification_max_rounds)

    def _prepare_clarification_or_force(self, session: Session, raw_clarification: dict) -> bool:
        """Returns True when SQL generation should retry (force finalize path)."""
        clarification = self._build_clarification_state(raw_clarification)
        clarification = attach_clarification_plan_and_progress(
            clarification,
            question=self.chat_question.question or '',
            schema_text=self._get_schema_text(),
            time_clarification_enabled=settings.TIME_RANGE_CLARIFICATION_ENABLED,
        )
        clarification['source_question'] = self.chat_question.question or ''
        clarification['source_schema'] = self._get_schema_text()
        if should_force_finalize(clarification):
            clarification['force_finalized'] = True
            self.record = save_clarification_state(session, self.record.id, clarification)
            self._force_clarification_finalize = True
            return True
        self.record = save_clarification_state(session, self.record.id, clarification)
        return False

    def _yield_clarification_sse(self, in_chat: bool, clarification: Optional[dict] = None):
        payload = clarification if clarification is not None else self.record.clarification
        if not in_chat or not payload:
            return
        yield 'data:' + orjson.dumps({
            'type': 'clarification',
            'content': payload,
            'record_id': self.record.id,
        }).decode() + '\n\n'
        yield 'data:' + orjson.dumps({'type': 'clarification-pending'}).decode() + '\n\n'

    def _regenerate_sql_for_time_filter(self, session: Session, reason: str, in_chat: bool):
        """Re-run LLM SQL generation after time-filter validation failed. Yields SSE chunks; returns full text."""
        earliest = get_query_earliest_date(session)
        inferred = self._inferred_time_range or {}
        bound_hint = ''
        if inferred.get('date_start') and inferred.get('date_end'):
            bound_hint = (
                f'请严格使用开始日期 {inferred["date_start"]}、结束日期 {inferred["date_end"]}'
                f'（{inferred.get("label") or inferred.get("field") or ""}）过滤。\n'
            )
        self.sql_message.append(HumanMessage(
            content=(
                f'<sql-time-filter-required>\n{reason}\n'
                f'{bound_hint}'
                f'数据最早可查日：{earliest}。必须在 SQL 的 WHERE 或子查询中加入时间字段过滤。\n'
                f'</sql-time-filter-required>'
            )
        ))
        self.sql_message.append(AIMessage(content='我将补充时间范围过滤条件后重新生成 SQL。'))
        full_sql_text = ''
        token_usage = {}
        res = process_stream(self.llm.stream(self.sql_message), token_usage)
        for chunk in res:
            if chunk.get('content'):
                full_sql_text += chunk.get('content')
            if in_chat:
                yield 'data:' + orjson.dumps({
                    'content': chunk.get('content'),
                    'reasoning_content': chunk.get('reasoning_content'),
                    'type': 'sql-result',
                }).decode() + '\n\n'
        self.sql_message.append(AIMessage(full_sql_text))
        self.record = save_sql_answer(
            session=session,
            record_id=self.record.id,
            answer=orjson.dumps({'content': full_sql_text}).decode(),
        )

    def _resolve_sql_for_execution(
        self,
        session: Session,
        full_sql_text: str,
        sql_operate: OperationEnum,
        use_dynamic_ds: bool,
        is_page_embedded: bool,
    ) -> dict:
        """Parse LLM answer, apply row permissions / dynamic SQL, return executable SQL."""
        sql, tables = self.check_sql(session=session, res=full_sql_text, operate=sql_operate)
        dynamic_sql_result = None
        sqlbot_temp_sql_text = None
        assistant_dynamic_sql = None

        if ((not self.current_assistant or is_page_embedded) and is_normal_user(
                self.current_user)) or use_dynamic_ds:
            sql_result = None
            if use_dynamic_ds:
                dynamic_sql_result = self.generate_assistant_dynamic_sql(session, sql, tables)
                sqlbot_temp_sql_text = (
                    dynamic_sql_result.get('sqlbot_temp_sql_text') if dynamic_sql_result else None
                )
            else:
                sql_result = self.generate_filter(session, sql, tables)

            if sql_result:
                SQLBotLogUtil.info(sql_result)
                sql_operate = OperationEnum.GENERATE_SQL_WITH_PERMISSIONS
                sql = self.check_save_sql(session=session, res=sql_result, operate=sql_operate)
            elif dynamic_sql_result and sqlbot_temp_sql_text:
                sql_operate = OperationEnum.GENERATE_DYNAMIC_SQL
                assistant_dynamic_sql = self.check_save_sql(
                    session=session, res=sqlbot_temp_sql_text, operate=sql_operate,
                )
            else:
                sql = self.check_save_sql(session=session, res=full_sql_text, operate=sql_operate)
        else:
            sql = self.check_save_sql(session=session, res=full_sql_text, operate=sql_operate)

        real_execute_sql = sql
        if sqlbot_temp_sql_text and assistant_dynamic_sql and dynamic_sql_result:
            dynamic_sql_result.pop('sqlbot_temp_sql_text')
            for origin_table, subsql in dynamic_sql_result.items():
                assistant_dynamic_sql = assistant_dynamic_sql.replace(
                    f'{dynamic_subsql_prefix}{origin_table}', subsql,
                )
            real_execute_sql = assistant_dynamic_sql

        self.chat_question.sql = sql
        return {
            'sql': sql,
            'tables': tables,
            'real_execute_sql': real_execute_sql,
            'sql_operate': sql_operate,
        }

    def _regenerate_sql_for_exec_error(
        self,
        session: Session,
        failed_sql: str,
        error_text: str,
        in_chat: bool,
    ):
        """Re-run LLM with execution error context; yields SSE chunks."""
        self.sql_message.append(HumanMessage(content=(
            f'<sql-execution-error>\n'
            f'以下 SQL 在数据库执行失败，请根据报错与 m-schema 修正后重新输出完整 JSON（success:true 含 sql 字段）。\n'
            f'失败的 SQL：\n{failed_sql}\n\n'
            f'数据库报错：\n{error_text}\n'
            f'</sql-execution-error>'
        )))
        self.sql_message.append(AIMessage(content='我将根据执行报错修正 SQL 后重新生成。'))
        full_sql_text = ''
        token_usage = {}
        res = process_stream(self.llm.stream(self.sql_message), token_usage)
        for chunk in res:
            if chunk.get('content'):
                full_sql_text += chunk.get('content')
            if in_chat:
                yield 'data:' + orjson.dumps({
                    'content': chunk.get('content'),
                    'reasoning_content': chunk.get('reasoning_content'),
                    'type': 'sql-result',
                }).decode() + '\n\n'
        self.sql_message.append(AIMessage(full_sql_text))
        self.record = save_sql_answer(
            session=session,
            record_id=self.record.id,
            answer=orjson.dumps({'content': full_sql_text}).decode(),
        )

    def execute_sql(self, sql: str):
        """Execute SQL query

        Args:
            ds: Data source instance
            sql: SQL query statement

        Returns:
            Query results
        """
        SQLBotLogUtil.info(f"Executing SQL on ds_id {self.ds.id}: {sql}")
        try:
            return exec_sql(ds=self.ds, sql=sql, origin_column=False)
        except Exception as e:
            if isinstance(e, ParseSQLResultError):
                raise e
            else:
                err = traceback.format_exc(limit=1, chain=True)
                raise SQLBotDBError(err)

    def pop_chunk(self):
        try:
            chunk = self.chunk_list.pop(0)
            return chunk
        except IndexError as e:
            return None

    def await_result(self):
        while self.is_running():
            while True:
                chunk = self.pop_chunk()
                if chunk is not None:
                    yield chunk
                else:
                    break
        while True:
            chunk = self.pop_chunk()
            if chunk is None:
                break
            yield chunk

    def run_task_async(self, in_chat: bool = True, stream: bool = True,
                       finish_step: ChatFinishStep = ChatFinishStep.GENERATE_CHART, return_img: bool = True):
        if in_chat:
            stream = True
        self.future = executor.submit(self.run_task_cache, in_chat, stream, finish_step, return_img)

    def run_task_cache(self, in_chat: bool = True, stream: bool = True,
                       finish_step: ChatFinishStep = ChatFinishStep.GENERATE_CHART, return_img: bool = True):
        for chunk in self.run_task(in_chat, stream, finish_step, return_img):
            self.chunk_list.append(chunk)

    def run_task(self, in_chat: bool = True, stream: bool = True,
                 finish_step: ChatFinishStep = ChatFinishStep.GENERATE_CHART, return_img: bool = True):
        json_result: Dict[str, Any] = {'success': True}
        _session = None
        try:
            _session = session_maker()
            if self.record and self.record.id:
                db_record = get_chat_record_by_id(_session, self.record.id)
                if db_record:
                    self.record = db_record
            if self.ds:
                oid = self.ds.oid if isinstance(self.ds, CoreDatasource) else 1
                ds_id = self.ds.id if isinstance(self.ds, CoreDatasource) else None

                self.filter_terminology_template(_session, oid, ds_id)

                self.filter_training_template(_session, oid, ds_id)

                self.filter_custom_prompts(_session, CustomPromptTypeEnum.GENERATE_SQL, oid, ds_id)

                self.init_messages(_session)

            # return id
            if in_chat:
                yield 'data:' + orjson.dumps({'type': 'id', 'id': self.get_record().id}).decode() + '\n\n'
                if self.get_record().regenerate_record_id:
                    yield 'data:' + orjson.dumps({'type': 'regenerate_record_id',
                                                  'regenerate_record_id': self.get_record().regenerate_record_id}).decode() + '\n\n'
                yield 'data:' + orjson.dumps(
                    {'type': 'question', 'question': self.get_record().question}).decode() + '\n\n'
            else:
                if stream:
                    yield '> ' + self.trans('i18n_chat.record_id_in_mcp') + str(self.get_record().id) + '\n'
                    yield '> ' + self.get_record().question + '\n\n'
            if not stream:
                json_result['record_id'] = self.get_record().id

                # select datasource if datasource is none
            if not self.ds:
                ds_res = self.select_datasource(_session)

                for chunk in ds_res:
                    SQLBotLogUtil.info(chunk)
                    if in_chat:
                        yield 'data:' + orjson.dumps(
                            {'content': chunk.get('content'), 'reasoning_content': chunk.get('reasoning_content'),
                             'type': 'datasource-result'}).decode() + '\n\n'
                if in_chat:
                    yield 'data:' + orjson.dumps({'id': self.ds.id, 'datasource_name': self.ds.name,
                                                  'engine_type': self.ds.type_name or self.ds.type,
                                                  'type': 'datasource'}).decode() + '\n\n'

            else:
                self.validate_history_ds(_session)

            # check connection
            connected = check_connection(ds=self.ds, trans=None)
            if not connected:
                raise SQLBotDBConnectionError('Connect DB failed')

            # generate sql
            full_sql_text = ''
            clarification = self.record.clarification if isinstance(self.record.clarification, dict) else {}
            if clarification.get('resolved') and not clarification.get('current'):
                SQLBotLogUtil.info(
                    f'generate sql after clarification record={self.record.id} '
                    f'resolved={[r.get("field") for r in (clarification.get("resolved") or [])]}'
                )
            while True:
                try:
                    sql_res = self.generate_sql(_session)
                    full_sql_text = ''
                    for chunk in sql_res:
                        full_sql_text += chunk.get('content')
                        if in_chat:
                            yield 'data:' + orjson.dumps(
                                {'content': chunk.get('content'),
                                 'reasoning_content': chunk.get('reasoning_content'),
                                 'type': 'sql-result'}).decode() + '\n\n'
                    if in_chat:
                        yield 'data:' + orjson.dumps({'type': 'info', 'msg': 'sql generated'}).decode() + '\n\n'
                    SQLBotLogUtil.info(full_sql_text)
                    chart_type = self.get_chart_type_from_sql_answer(full_sql_text)
                    break
                except ClarificationRequiredError as cle:
                    if self._prepare_clarification_or_force(_session, cle.clarification):
                        continue
                    clarification_state = (
                        self.record.clarification
                        if isinstance(self.record.clarification, dict)
                        else None
                    )
                    for item in self._yield_clarification_sse(in_chat, clarification_state):
                        yield item
                    if in_chat:
                        yield 'data:' + orjson.dumps({'type': 'finish'}).decode() + '\n\n'
                    return

            # return title
            if self.change_title:
                llm_brief = self.get_brief_from_sql_answer(full_sql_text)
                llm_brief_generated = bool(llm_brief)
                if llm_brief_generated or (self.chat_question.question and self.chat_question.question.strip() != ''):
                    save_brief = llm_brief if (llm_brief and llm_brief != '') else self.chat_question.question.strip()[
                                                                                   :20]
                    brief = rename_chat(session=_session,
                                        rename_object=RenameChat(id=self.get_record().chat_id,
                                                                 brief=save_brief, brief_generate=llm_brief_generated))
                    if in_chat:
                        yield 'data:' + orjson.dumps({'type': 'brief', 'brief': brief}).decode() + '\n\n'
                    if not stream:
                        json_result['title'] = brief

            use_dynamic_ds: bool = self.current_assistant and self.current_assistant.type in dynamic_ds_types
            is_page_embedded: bool = self.current_assistant and self.current_assistant.type == 4

            sql_operate = OperationEnum.GENERATE_SQL
            resolved = self._resolve_sql_for_execution(
                _session, full_sql_text, sql_operate, use_dynamic_ds, is_page_embedded,
            )
            sql = resolved['sql']
            tables = resolved['tables']
            real_execute_sql = resolved['real_execute_sql']
            sql_operate = resolved['sql_operate']

            if settings.SQL_TIME_FILTER_VALIDATION_ENABLED:
                schema = self._get_schema_text()
                clarification = (
                    self.record.clarification if isinstance(self.record.clarification, dict) else {}
                )
                time_resolved = get_time_range_resolved(clarification) or self._inferred_time_range
                used_tables: set[str] = set()
                if tables:
                    used_tables.update(str(t) for t in tables if t)
                used_tables |= extract_sql_table_names(sql)
                ds_id = self.ds.id if isinstance(self.ds, CoreDatasource) else None
                tables_matched, role_time_fields = resolve_time_role_fields_for_tables(
                    _session, ds_id, used_tables,
                )
                # Tables resolved and none have semantic_role=time → skip hard check.
                # Otherwise validate (role fields when matched; schema name heuristic as fallback).
                skip_time_filter = tables_matched and not role_time_fields
                if skip_time_filter:
                    SQLBotLogUtil.info(
                        f'sql time filter skipped record={self.record.id} '
                        f'reason=no_time_role_fields tables={sorted(used_tables)}'
                    )
                if not skip_time_filter:
                    for attempt in range(settings.SQL_TIME_FILTER_MAX_RETRIES + 1):
                        ok, reason = sql_has_time_filter(
                            sql,
                            schema,
                            time_resolved,
                            required_time_fields=role_time_fields if tables_matched else None,
                            tables_matched=tables_matched,
                        )
                        if ok:
                            break
                        if attempt >= settings.SQL_TIME_FILTER_MAX_RETRIES:
                            raise SingleMessageError(orjson.dumps({
                                'message': '生成的 SQL 未包含时间范围过滤，请补充时间后重试',
                            }).decode())
                        SQLBotLogUtil.info(
                            f'sql time filter retry record={self.record.id} '
                            f'attempt={attempt + 1} reason={reason}'
                        )
                        if in_chat:
                            yield 'data:' + orjson.dumps({
                                'type': 'info',
                                'msg': 'SQL 缺少时间过滤，正在重新生成…',
                            }).decode() + '\n\n'
                        for chunk in self._regenerate_sql_for_time_filter(_session, reason, in_chat):
                            yield chunk
                        self.record = get_chat_record_by_id(_session, self.record.id)
                        raw_answer = self.record.sql_answer or ''
                        try:
                            full_sql_text = orjson.loads(raw_answer).get('content', raw_answer)
                        except Exception:
                            full_sql_text = raw_answer
                        resolved = self._resolve_sql_for_execution(
                            _session, full_sql_text, sql_operate, use_dynamic_ds, is_page_embedded,
                        )
                        sql = resolved['sql']
                        tables = resolved['tables']
                        real_execute_sql = resolved['real_execute_sql']
                        sql_operate = resolved['sql_operate']
                        used_tables = set()
                        if tables:
                            used_tables.update(str(t) for t in tables if t)
                        used_tables |= extract_sql_table_names(sql)
                        tables_matched, role_time_fields = resolve_time_role_fields_for_tables(
                            _session, ds_id, used_tables,
                        )
                        if tables_matched and not role_time_fields:
                            break

            if isinstance(self.record.clarification, dict) and self.record.clarification:
                done_state = {**self.record.clarification, 'current': None}
                self.record = save_clarification_state(
                    _session, self.record.id, done_state, resolved=True, abandoned=False)

            SQLBotLogUtil.info('sql: ' + sql)

            if not stream:
                json_result['sql'] = sql

            format_sql = sqlparse.format(sql, reindent=True)
            if in_chat:
                yield 'data:' + orjson.dumps({'content': format_sql, 'type': 'sql'}).decode() + '\n\n'
            else:
                if stream:
                    yield f'```sql\n{format_sql}\n```\n\n'

            if finish_step.value <= ChatFinishStep.GENERATE_SQL.value:
                if in_chat:
                    yield 'data:' + orjson.dumps({'type': 'finish'}).decode() + '\n\n'
                if not stream:
                    yield json_result
                return

            result = None
            max_exec_retries = settings.SQL_EXECUTE_MAX_RETRIES
            for exec_attempt in range(max_exec_retries + 1):
                try:
                    self.current_logs[OperationEnum.EXECUTE_SQL] = start_log(
                        session=_session,
                        operate=OperationEnum.EXECUTE_SQL,
                        record_id=self.record.id,
                        local_operation=True,
                    )
                    result = self.execute_sql(sql=real_execute_sql)
                    self.current_logs[OperationEnum.EXECUTE_SQL] = end_log(
                        session=_session,
                        log=self.current_logs[OperationEnum.EXECUTE_SQL],
                        full_message={'sql': real_execute_sql, 'count': len(result.get('data'))},
                    )
                    break
                except (SQLBotDBError, ParseSQLResultError) as exec_err:
                    if exec_attempt >= max_exec_retries:
                        raise
                    error_text = str(exec_err)
                    SQLBotLogUtil.info(
                        f'sql execute retry record={self.record.id} '
                        f'attempt={exec_attempt + 1}/{max_exec_retries} error={error_text[:500]}'
                    )
                    if in_chat:
                        yield 'data:' + orjson.dumps({
                            'type': 'info',
                            'msg': f'SQL 执行失败，正在根据报错重新生成（{exec_attempt + 1}/{max_exec_retries}）…',
                        }).decode() + '\n\n'
                    for chunk in self._regenerate_sql_for_exec_error(
                        _session, real_execute_sql, error_text, in_chat,
                    ):
                        yield chunk
                    self.record = get_chat_record_by_id(_session, self.record.id)
                    raw_answer = self.record.sql_answer or ''
                    try:
                        full_sql_text = orjson.loads(raw_answer).get('content', raw_answer)
                    except Exception:
                        full_sql_text = raw_answer
                    resolved = self._resolve_sql_for_execution(
                        _session, full_sql_text, sql_operate, use_dynamic_ds, is_page_embedded,
                    )
                    sql = resolved['sql']
                    tables = resolved['tables']
                    real_execute_sql = resolved['real_execute_sql']
                    sql_operate = resolved['sql_operate']
                    format_sql = sqlparse.format(sql, reindent=True)
                    if in_chat:
                        yield 'data:' + orjson.dumps({
                            'content': format_sql, 'type': 'sql',
                        }).decode() + '\n\n'

            _data = DataFormat.convert_large_numbers_in_object_array(result.get('data'))
            result["data"] = _data

            self.save_sql_data(session=_session, data_obj=result)
            if in_chat:
                yield 'data:' + orjson.dumps({'content': 'execute-success', 'type': 'sql-data'}).decode() + '\n\n'
            if not stream:
                json_result['data'] = get_chat_chart_data(_session, self.record.id)

            # BlueCard: field display aliases (terminology dict > LLM zh/en)
            fields_for_alias = result.get('fields') or []
            if in_chat and fields_for_alias:
                try:
                    alias_list = self.generate_field_aliases(_session, fields_for_alias)
                    yield 'data:' + orjson.dumps({
                        'type': 'field-aliases',
                        'content': alias_list,
                    }).decode() + '\n\n'
                except Exception as alias_err:
                    SQLBotLogUtil.warning(
                        f'bluecard field_aliases failed record={self.record.id} err={alias_err}'
                    )

            # BlueCard P1: multi-row summary SSE before chart generation
            row_count = len(result.get('data') or [])
            if in_chat and row_count > 1 and finish_step.value > ChatFinishStep.QUERY_DATA.value:
                try:
                    for chunk in self.generate_summary(_session, result):
                        if in_chat:
                            yield 'data:' + orjson.dumps({
                                'content': chunk.get('content') or '',
                                'reasoning_content': chunk.get('reasoning_content') or '',
                                'type': 'summary-result',
                            }).decode() + '\n\n'
                    if self.record.summary:
                        yield 'data:' + orjson.dumps({
                            'content': self.record.summary,
                            'type': 'summary',
                        }).decode() + '\n\n'
                except Exception as summary_err:
                    SQLBotLogUtil.warning(
                        f'bluecard summary failed record={self.record.id} err={summary_err}'
                    )

            if finish_step.value <= ChatFinishStep.QUERY_DATA.value:
                if stream:
                    if in_chat:
                        yield 'data:' + orjson.dumps({'type': 'finish'}).decode() + '\n\n'
                    else:
                        _column_list = []
                        for field in result.get('fields'):
                            _column_list.append(AxisObj(name=field, value=field))

                        md_data, _fields_list = DataFormat.convert_object_array_for_pandas(_column_list,
                                                                                           result.get('data'))

                        # data, _fields_list, col_formats = self.format_pd_data(_column_list, result.get('data'))

                        if not _data or not _fields_list:
                            yield 'The SQL execution result is empty.\n\n'
                        else:
                            df = pd.DataFrame(_data, columns=_fields_list)
                            df_safe = DataFormat.safe_convert_to_string(df)
                            markdown_table = df_safe.to_markdown(index=False)
                            yield markdown_table + '\n\n'
                else:
                    yield json_result
                return

            # BlueCard P2: layout plan — skip chart LLM for cards / force table when unvisualizable
            fields_list = result.get('fields') or []
            rows_list = result.get('data') or []
            plan = plan_bluecard_result(
                fields_list,
                rows_list,
                preferred_chart_type=chart_type,
                title=(self.chat_question.question or '')[:40],
            )
            SQLBotLogUtil.info(
                f'bluecard plan record={self.record.id} layout={plan.layout} '
                f'skip_chart={plan.skip_chart} force_table={plan.force_table} '
                f'chart_type={plan.chart_type} rows={plan.row_count}'
            )
            if in_chat:
                yield 'data:' + orjson.dumps({
                    'type': 'layout',
                    'layout': plan.layout,
                    'skip_chart': plan.skip_chart,
                    'force_table': plan.force_table,
                }).decode() + '\n\n'

            if plan.skip_chart:
                if plan.force_table:
                    chart = build_table_chart_config(
                        fields_list,
                        rows_list,
                        title=(self.chat_question.question or '')[:40] or '查询结果',
                    )
                    save_chart(
                        session=_session,
                        chart=orjson.dumps(chart).decode(),
                        record_id=self.record.id,
                    )
                    if not stream:
                        json_result['chart'] = chart
                    if in_chat:
                        yield 'data:' + orjson.dumps({
                            'content': orjson.dumps(chart).decode(),
                            'type': 'chart',
                        }).decode() + '\n\n'
                # single-row / empty: no chart LLM; frontend bluecard uses sql-data only
                if in_chat:
                    yield 'data:' + orjson.dumps({'type': 'finish'}).decode() + '\n\n'
                elif stream:
                    _column_list = [AxisObj(name=f, value=f) for f in fields_list]
                    md_data, _fields_list = DataFormat.convert_object_array_for_pandas(
                        _column_list, rows_list,
                    )
                    if md_data and _fields_list:
                        df = pd.DataFrame(md_data, columns=_fields_list)
                        df_safe = DataFormat.safe_convert_to_string(df)
                        yield df_safe.to_markdown(index=False) + '\n\n'
                    else:
                        yield 'The SQL execution result is empty.\n\n'
                else:
                    yield json_result
                return

            # generate chart (multi-row visualizable)
            used_tables_schema = self.out_ds_instance.get_db_schema(
                self.ds.id, self.chat_question.question, embedding=False,
                table_list=tables) if self.out_ds_instance else get_table_schema(
                session=_session,
                current_user=self.current_user,
                ds=self.ds,
                question=self.chat_question.question,
                embedding=False, table_list=tables)
            SQLBotLogUtil.info('used_tables_schema: \n' + used_tables_schema)
            chart_res = self.generate_chart(_session, plan.chart_type or chart_type, used_tables_schema)
            full_chart_text = ''
            for chunk in chart_res:
                full_chart_text += chunk.get('content')
                if in_chat:
                    yield 'data:' + orjson.dumps(
                        {'content': chunk.get('content'), 'reasoning_content': chunk.get('reasoning_content'),
                         'type': 'chart-result'}).decode() + '\n\n'
            if in_chat:
                yield 'data:' + orjson.dumps({'type': 'info', 'msg': 'chart generated'}).decode() + '\n\n'

            # filter chart
            SQLBotLogUtil.info(full_chart_text)
            chart = self.check_save_chart(session=_session, res=full_chart_text)
            SQLBotLogUtil.info(chart)

            if not stream:
                json_result['chart'] = chart

            if in_chat:
                yield 'data:' + orjson.dumps(
                    {'content': orjson.dumps(chart).decode(), 'type': 'chart'}).decode() + '\n\n'
            else:
                if stream:
                    md_data, _fields_list = DataFormat.convert_data_fields_for_pandas(chart, result.get('fields'),
                                                                                      result.get('data'))
                    # data, _fields_list, col_formats = self.format_pd_data(_column_list, result.get('data'))

                    if not md_data or not _fields_list:
                        yield 'The SQL execution result is empty.\n\n'
                    else:
                        df = pd.DataFrame(md_data, columns=_fields_list)
                        df_safe = DataFormat.safe_convert_to_string(df)
                        markdown_table = df_safe.to_markdown(index=False)
                        yield markdown_table + '\n\n'

            if in_chat:
                yield 'data:' + orjson.dumps({'type': 'finish'}).decode() + '\n\n'
            else:
                # generate picture
                try:
                    if chart.get('type') != 'table' and return_img:
                        # yield '### generated chart picture\n\n'
                        self.current_logs[OperationEnum.GENERATE_PICTURE] = start_log(session=_session,
                                                                                      operate=OperationEnum.GENERATE_PICTURE,
                                                                                      record_id=self.record.id,
                                                                                      local_operation=True)
                        image_url, error = request_picture(self.record.chat_id, self.record.id, chart,
                                                           format_json_data(result))
                        SQLBotLogUtil.info(image_url)
                        if stream:
                            yield f'![{chart.get("type")}]({image_url})'
                        else:
                            json_result['image_url'] = image_url
                        if error is not None:
                            raise error

                        self.current_logs[OperationEnum.GENERATE_PICTURE] = end_log(session=_session,
                                                                                    log=self.current_logs[
                                                                                        OperationEnum.GENERATE_PICTURE],
                                                                                    full_message=image_url)
                except Exception as e:
                    if stream:
                        if chart.get('type') != 'table':
                            yield 'generate or fetch chart picture error.\n\n'
                        raise e

            if not stream:
                yield json_result

        except Exception as e:
            traceback.print_exc()
            error_msg: str
            if isinstance(e, SingleMessageError):
                error_msg = str(e)
            elif isinstance(e, SQLBotDBConnectionError):
                error_msg = orjson.dumps(
                    {'message': str(e), 'type': 'db-connection-err'}).decode()
            elif isinstance(e, SQLBotDBError):
                error_msg = orjson.dumps(
                    {'message': 'Execute SQL Failed', 'traceback': str(e), 'type': 'exec-sql-err'}).decode()
            else:
                error_msg = orjson.dumps({'message': str(e), 'traceback': traceback.format_exc(limit=1)}).decode()
            if _session:
                self.save_error(session=_session, message=error_msg)
            if in_chat:
                yield 'data:' + orjson.dumps({'content': error_msg, 'type': 'error'}).decode() + '\n\n'
                yield 'data:' + orjson.dumps({'type': 'finish'}).decode() + '\n\n'
            else:
                if stream:
                    yield f'&#x274c; **ERROR:**\n'
                    yield f'> {error_msg}\n'
                else:
                    json_result['success'] = False
                    json_result['message'] = error_msg
                    yield json_result
        finally:
            self.finish(_session)
            session_maker.remove()

    def run_recommend_questions_task_async(self):
        self.future = executor.submit(self.run_recommend_questions_task_cache)

    def run_recommend_questions_task_cache(self):
        for chunk in self.run_recommend_questions_task():
            self.chunk_list.append(chunk)

    def run_recommend_questions_task(self):
        try:
            _session = session_maker()
            res = self.generate_recommend_questions_task(_session)

            for chunk in res:
                if chunk.get('recommended_question'):
                    yield 'data:' + orjson.dumps(
                        {'content': chunk.get('recommended_question'),
                         'type': 'recommended_question'}).decode() + '\n\n'
                else:
                    yield 'data:' + orjson.dumps(
                        {'content': chunk.get('content'), 'reasoning_content': chunk.get('reasoning_content'),
                         'type': 'recommended_question_result'}).decode() + '\n\n'
        except Exception:
            traceback.print_exc()
        finally:
            session_maker.remove()

    def run_analysis_or_predict_task_async(self, session: Session, action_type: str, base_record: ChatRecord,
                                           in_chat: bool = True, stream: bool = True):
        self.set_record(save_analysis_predict_record(session, base_record, action_type))
        self.future = executor.submit(self.run_analysis_or_predict_task_cache, action_type, in_chat, stream)

    def run_analysis_or_predict_task_cache(self, action_type: str, in_chat: bool = True, stream: bool = True):
        for chunk in self.run_analysis_or_predict_task(action_type, in_chat, stream):
            self.chunk_list.append(chunk)

    def run_analysis_or_predict_task(self, action_type: str, in_chat: bool = True, stream: bool = True):
        json_result: Dict[str, Any] = {'success': True}
        _session = None
        try:
            _session = session_maker()
            if in_chat:
                yield 'data:' + orjson.dumps({'type': 'id', 'id': self.get_record().id}).decode() + '\n\n'
            else:
                if stream:
                    yield '> ' + self.trans('i18n_chat.record_id_in_mcp') + str(self.get_record().id) + '\n'
                    yield '> ' + self.get_record().question + '\n\n'
            if not stream:
                json_result['record_id'] = self.get_record().id

            if action_type == 'analysis':
                # generate analysis
                analysis_res = self.generate_analysis(_session)
                full_text = ''
                for chunk in analysis_res:
                    full_text += chunk.get('content')
                    if in_chat:
                        yield 'data:' + orjson.dumps(
                            {'content': chunk.get('content'), 'reasoning_content': chunk.get('reasoning_content'),
                             'type': 'analysis-result'}).decode() + '\n\n'
                    else:
                        if stream:
                            yield chunk.get('content')
                if in_chat:
                    yield 'data:' + orjson.dumps({'type': 'info', 'msg': 'analysis generated'}).decode() + '\n\n'
                    yield 'data:' + orjson.dumps({'type': 'analysis_finish'}).decode() + '\n\n'
                else:
                    if stream:
                        yield '\n\n'
                if not stream:
                    json_result['content'] = full_text

            elif action_type == 'predict':
                # generate predict
                analysis_res = self.generate_predict(_session)
                full_text = ''
                for chunk in analysis_res:
                    full_text += chunk.get('content')
                    if in_chat:
                        yield 'data:' + orjson.dumps(
                            {'content': chunk.get('content'), 'reasoning_content': chunk.get('reasoning_content'),
                             'type': 'predict-result'}).decode() + '\n\n'
                if in_chat:
                    yield 'data:' + orjson.dumps({'type': 'info', 'msg': 'predict generated'}).decode() + '\n\n'

                has_data = self.check_save_predict_data(session=_session, res=full_text)
                if has_data:
                    if in_chat:
                        yield 'data:' + orjson.dumps({'type': 'predict-success'}).decode() + '\n\n'
                    else:
                        chart = get_chat_chart_config(_session, self.record.id)
                        origin_data = get_chat_chart_data(_session, self.record.id)
                        predict_data = get_chat_predict_data(_session, self.record.id)

                        if stream:
                            md_data, _fields_list = DataFormat.convert_data_fields_for_pandas(chart,
                                                                                              origin_data.get('fields'),
                                                                                              predict_data)
                            if not md_data or not _fields_list:
                                yield 'Predict data result is empty.\n\n'
                            else:
                                df = pd.DataFrame(md_data, columns=_fields_list)
                                df_safe = DataFormat.safe_convert_to_string(df)
                                markdown_table = df_safe.to_markdown(index=False)
                                yield markdown_table + '\n\n'

                        else:
                            json_result['origin_data'] = origin_data
                            json_result['predict_data'] = predict_data

                        # generate picture
                        try:
                            if chart.get('type') != 'table':
                                # yield '### generated chart picture\n\n'

                                _data = get_chat_chart_data(_session, self.record.id)
                                _data['data'] = _data.get('data') + predict_data

                                image_url, error = request_picture(self.record.chat_id, self.record.id, chart,
                                                                   format_json_data(_data))
                                SQLBotLogUtil.info(image_url)
                                if stream:
                                    yield f'![{chart.get("type")}]({image_url})'
                                else:
                                    json_result['image_url'] = image_url
                                if error is not None:
                                    raise error
                        except Exception as e:
                            if stream:
                                if chart.get('type') != 'table':
                                    yield 'generate or fetch chart picture error.\n\n'
                                raise e
                else:
                    if in_chat:
                        yield 'data:' + orjson.dumps({'type': 'predict-failed'}).decode() + '\n\n'
                    else:
                        if stream:
                            yield full_text + '\n\n'
                    if not stream:
                        json_result['success'] = False
                        json_result['message'] = full_text
                if in_chat:
                    yield 'data:' + orjson.dumps({'type': 'predict_finish'}).decode() + '\n\n'

            self.finish(_session)

            if not stream:
                yield json_result
        except Exception as e:
            traceback.print_exc()
            error_msg: str
            if isinstance(e, SingleMessageError):
                error_msg = str(e)
            else:
                error_msg = orjson.dumps({'message': str(e), 'traceback': traceback.format_exc(limit=1)}).decode()
            if _session:
                self.save_error(session=_session, message=error_msg)
            if in_chat:
                yield 'data:' + orjson.dumps({'content': error_msg, 'type': 'error'}).decode() + '\n\n'
            else:
                if stream:
                    yield f'&#x274c; **ERROR:**\n'
                    yield f'> {error_msg}\n'
                else:
                    json_result['success'] = False
                    json_result['message'] = error_msg
                    yield json_result
        finally:
            # end
            session_maker.remove()

    def validate_history_ds(self, session: Session):
        _ds = self.ds
        if not self.current_assistant or self.current_assistant.type == 4:
            try:
                current_ds = session.get(CoreDatasource, _ds.id)
                if not current_ds:
                    raise SingleMessageError('chat.ds_is_invalid')
            except Exception as e:
                raise SingleMessageError("chat.ds_is_invalid")
        else:
            try:
                _ds_list: list[dict] = get_assistant_ds(session=session, llm_service=self)
                match_ds = any(item.get("id") == _ds.id for item in _ds_list)
                if not match_ds:
                    type = self.current_assistant.type
                    msg = f"[please check ds list and public ds list]" if type == 0 else f"[please check ds api]"
                    raise SingleMessageError(msg)
            except Exception as e:
                raise SingleMessageError(f"ds is invalid [{str(e)}]")


def execute_sql_with_db(db: SQLDatabase, sql: str) -> str:
    """Execute SQL query using SQLDatabase

    Args:
        db: SQLDatabase instance
        sql: SQL query statement

    Returns:
        str: Query results formatted as string
    """
    try:
        # Execute query
        result = db.run(sql)

        if not result:
            return "Query executed successfully but returned no results."

        # Format results
        return str(result)

    except Exception as e:
        error_msg = f"SQL execution failed: {str(e)}"
        SQLBotLogUtil.exception(error_msg)
        raise RuntimeError(error_msg)


def request_picture(chat_id: int, record_id: int, chart: dict, data: dict):
    file_name = f'c_{chat_id}_r_{record_id}'

    columns = chart.get('columns') if chart.get('columns') else []
    x = None
    y = None
    series = None
    multi_quota_fields = []
    multi_quota_name = None

    if chart.get('axis'):
        axis_data = chart.get('axis')
        x = axis_data.get('x')
        y = axis_data.get('y')
        series = axis_data.get('series')
        # 获取multi-quota字段列表
        if axis_data.get('multi-quota') and 'value' in axis_data.get('multi-quota'):
            multi_quota_fields = axis_data.get('multi-quota').get('value', [])
            multi_quota_name = axis_data.get('multi-quota').get('name')

    axis = []
    for v in columns:
        axis.append({'name': v.get('name'), 'value': v.get('value')})
    if x:
        axis.append({'name': x.get('name'), 'value': x.get('value'), 'type': 'x'})
    if y:
        y_list = y if isinstance(y, list) else [y]

        for y_item in y_list:
            if isinstance(y_item, dict) and 'value' in y_item:
                y_obj = {
                    'name': y_item.get('name'),
                    'value': y_item.get('value'),
                    'type': 'y'
                }
                # 如果是multi-quota字段，添加标志
                if y_item.get('value') in multi_quota_fields:
                    y_obj['multi-quota'] = True
                axis.append(y_obj)
    if series:
        axis.append({'name': series.get('name'), 'value': series.get('value'), 'type': 'series'})
    if multi_quota_name:
        axis.append({'name': multi_quota_name, 'value': multi_quota_name, 'type': 'other-info'})

    request_obj = {
        "path": os.path.join(settings.MCP_IMAGE_PATH, file_name),
        "type": chart.get('type'),
        "data": orjson.dumps(data.get('data') if data.get('data') else []).decode(),
        "axis": orjson.dumps(axis).decode(),
    }

    _error = None
    try:
        requests.post(url=settings.MCP_IMAGE_HOST, json=request_obj, timeout=settings.SERVER_IMAGE_TIMEOUT)
    except Exception as e:
        _error = e

    request_path = urllib.parse.urljoin(settings.SERVER_IMAGE_HOST, f"{file_name}.png")

    return request_path, _error


def get_token_usage(chunk: BaseMessageChunk, token_usage: dict = None):
    try:
        if chunk.usage_metadata:
            if token_usage is None:
                token_usage = {}
            token_usage['input_tokens'] = chunk.usage_metadata.get('input_tokens')
            token_usage['output_tokens'] = chunk.usage_metadata.get('output_tokens')
            token_usage['total_tokens'] = chunk.usage_metadata.get('total_tokens')
    except Exception:
        pass


def process_stream(res: Iterator[BaseMessageChunk],
                   token_usage: Dict[str, Any] = None,
                   enable_tag_parsing: bool = settings.PARSE_REASONING_BLOCK_ENABLED,
                   start_tag: str = settings.DEFAULT_REASONING_CONTENT_START,
                   end_tag: str = settings.DEFAULT_REASONING_CONTENT_END
                   ):
    if token_usage is None:
        token_usage = {}
    in_thinking_block = False  # 标记是否在思考过程块中
    current_thinking = ''  # 当前收集的思考过程内容
    pending_start_tag = ''  # 用于缓存可能被截断的开始标签部分

    for chunk in res:
        SQLBotLogUtil.info(chunk)
        reasoning_content_chunk = ''
        content = chunk.content
        output_content = ''  # 实际要输出的内容

        # 检查additional_kwargs中的reasoning_content
        if 'reasoning_content' in chunk.additional_kwargs:
            reasoning_content = chunk.additional_kwargs.get('reasoning_content', '')
            if reasoning_content is None:
                reasoning_content = ''

            # 累积additional_kwargs中的思考内容到current_thinking
            current_thinking += reasoning_content
            reasoning_content_chunk = reasoning_content

        # 只有当current_thinking不是空字符串时才跳过标签解析
        if not in_thinking_block and current_thinking.strip() != '':
            output_content = content  # 正常输出content
            yield {
                'content': output_content,
                'reasoning_content': reasoning_content_chunk
            }
            get_token_usage(chunk, token_usage)
            continue  # 跳过后续的标签解析逻辑

        # 如果没有有效的思考内容，并且启用了标签解析，才执行标签解析逻辑
        # 如果有缓存的开始标签部分，先拼接当前内容
        if pending_start_tag:
            content = pending_start_tag + content
            pending_start_tag = ''

        # 检查是否开始思考过程块（处理可能被截断的开始标签）
        if enable_tag_parsing and not in_thinking_block and start_tag:
            if start_tag in content:
                start_idx = content.index(start_tag)
                # 只有当开始标签前面没有其他文本时才认为是真正的思考块开始
                if start_idx == 0 or content[:start_idx].strip() == '':
                    # 完整标签存在且前面没有其他文本
                    output_content += content[:start_idx]  # 输出开始标签之前的内容
                    content = content[start_idx + len(start_tag):]  # 移除开始标签
                    in_thinking_block = True
                else:
                    # 开始标签前面有其他文本，不认为是思考块开始
                    output_content += content
                    content = ''
            else:
                # 检查是否可能有部分开始标签
                for i in range(1, len(start_tag)):
                    if content.endswith(start_tag[:i]):
                        # 只有当当前内容全是空白时才缓存部分标签
                        if content[:-i].strip() == '':
                            pending_start_tag = start_tag[:i]
                            content = content[:-i]  # 移除可能的部分标签
                            output_content += content
                            content = ''
                        break

        # 处理思考块内容
        if enable_tag_parsing and in_thinking_block and end_tag:
            if end_tag in content:
                # 找到结束标签
                end_idx = content.index(end_tag)
                current_thinking += content[:end_idx]  # 收集思考内容
                reasoning_content_chunk += current_thinking  # 添加到当前块的思考内容
                content = content[end_idx + len(end_tag):]  # 移除结束标签后的内容
                current_thinking = ''  # 重置当前思考内容
                in_thinking_block = False
                output_content += content  # 输出结束标签之后的内容
            else:
                # 在遇到结束标签前，持续收集思考内容
                current_thinking += content
                reasoning_content_chunk += content
                content = ''

        else:
            # 不在思考块中或标签解析未启用，正常输出
            output_content += content

        yield {
            'content': output_content,
            'reasoning_content': reasoning_content_chunk
        }
        get_token_usage(chunk, token_usage)


def get_lang_name(lang: str):
    if not lang:
        return '简体中文'
    normalized = lang.lower()
    if normalized.startswith('zh-tw'):
        return '繁体中文'
    if normalized.startswith('en'):
        return '英文'
    if normalized.startswith('ko'):
        return '韩语'
    return '简体中文'


def get_last_conversation_rounds(messages, rounds=settings.GENERATE_SQL_QUERY_HISTORY_ROUND_COUNT):
    """获取最后N轮对话，处理不完整对话的情况"""
    if not messages or rounds <= 0:
        return []

    # 找到所有用户消息的位置
    human_indices = []
    for index, msg in enumerate(messages):
        if msg.get('type') == 'human':
            human_indices.append(index)

    # 如果没有用户消息，返回空
    if not human_indices:
        return []

    # 计算从哪个索引开始
    if len(human_indices) <= rounds:
        # 如果用户消息数少于等于需要的轮数，从第一个用户消息开始
        start_index = human_indices[0]
    else:
        # 否则，从倒数第N个用户消息开始
        start_index = human_indices[-rounds]

    return messages[start_index:]
