from common.core.deps import SessionDep
from ..models.datasource import CoreField, FieldObj
from sqlalchemy import or_, and_


def delete_field_by_ds_id(session: SessionDep, id: int):
    session.query(CoreField).filter(CoreField.ds_id == id).delete(synchronize_session=False)
    session.commit()


def get_fields_by_table_id(session: SessionDep, id: int, field: FieldObj):
    if field and field.fieldName:
        return session.query(CoreField).filter(
            and_(CoreField.table_id == id, or_(CoreField.field_name.like(f'%{field.fieldName}%'),
                                               CoreField.field_name.like(f'%{field.fieldName.lower()}%'),
                                               CoreField.field_name.like(f'%{field.fieldName.upper()}%')))).order_by(
            CoreField.field_index.asc()).all()
    else:
        return session.query(CoreField).filter(CoreField.table_id == id).order_by(CoreField.field_index.asc()).all()


def update_field(session: SessionDep, item: CoreField):
    from apps.datasource.crud.llm_preview import normalize_role

    record = session.query(CoreField).filter(CoreField.id == item.id).first()
    if record is None:
        return
    record.checked = item.checked
    record.custom_comment = item.custom_comment

    new_role = None
    if hasattr(item, 'semantic_role'):
        new_role = normalize_role(item.semantic_role)
        if new_role == 'pk':
            # only one pk per table
            others = session.query(CoreField).filter(
                and_(CoreField.table_id == record.table_id, CoreField.id != record.id,
                     CoreField.semantic_role == 'pk')
            ).all()
            for other in others:
                other.semantic_role = None
                session.add(other)
        if record.semantic_role != new_role:
            from apps.datasource.crud.llm_preview import clear_table_llm_preview
            clear_table_llm_preview(session, record.table_id, commit=False)
        record.semantic_role = new_role

    session.add(record)
    session.commit()
