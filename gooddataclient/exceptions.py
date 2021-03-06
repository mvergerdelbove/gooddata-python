

class GoodDataClientError(Exception):

    def __init__(self, msg, **kwargs):
        self.msg = msg
        self.error_info = kwargs

    def __str__(self):
        return repr(self.msg % self.error_info)


class AuthenticationError(GoodDataClientError):
    pass


class ProjectCreationError(GoodDataClientError):
    pass


class ProjectNotOpenedError(GoodDataClientError):
    pass


class ProjectNotFoundError(GoodDataClientError):
    pass


class DataSetNotFoundError(GoodDataClientError):
    pass


class UploadFailed(GoodDataClientError):
    pass


class MaqlExecutionFailed(GoodDataClientError):
    pass


class DMLExecutionFailed(MaqlExecutionFailed):
    pass


class MaqlValidationFailed(GoodDataClientError):
    pass


class GetSLIManifestFailed(GoodDataClientError):
    pass


class MigrationFailed(GoodDataClientError):
    pass


class GoodDataTotallyDown(GoodDataClientError):
    def __init__(self, err, **kwargs):
        self.msg = str(err.__class__.__name__) + ': ' + str(err)
        self.error_info = kwargs


class InvalidAPIQuery(GoodDataClientError):
    pass


class ReportExecutionFailed(GoodDataClientError):
    pass


class ReportExportFailed(GoodDataClientError):
    pass


class ReportRetrievalFailed(GoodDataClientError):
    pass


class DashboardExportError(GoodDataClientError):
    pass


class RowDeletionError(GoodDataClientError):
    pass


def get_api_msg(err_json):
    return err_json['message'] % tuple(err_json['parameters'])
