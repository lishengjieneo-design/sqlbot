class ClarificationRequiredError(Exception):
    def __init__(self, clarification: dict):
        super().__init__('clarification_required')
        self.clarification = clarification


class SingleMessageError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

    def __str__(self):
        return self.message


class SQLBotDBConnectionError(Exception):
    pass


class SQLBotDBError(Exception):
    pass


class ParseSQLResultError(Exception):
    pass
