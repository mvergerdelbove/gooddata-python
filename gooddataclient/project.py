import time
import logging

from requests.exceptions import HTTPError

from gooddataclient.exceptions import (
    ProjectNotOpenedError, UploadFailed, ProjectNotFoundError, MaqlExecutionFailed,
    get_api_msg, MaqlValidationFailed, ProjectCreationError, DMLExecutionFailed,
    GoodDataTotallyDown
)

logger = logging.getLogger("gooddataclient")


def delete_projects_by_name(connection, name):
    """Delete all GoodData projects by that name"""
    logger.debug('Dropping project by name %s' % name)
    try:
        while True:
            Project(connection).load(name=name).delete()
    except ProjectNotFoundError:
        pass


class Project(object):

    PROJECTS_URI = '/gdc/projects'
    MAQL_EXEC_URI = '/gdc/md/%s/ldm/manage2'
    MAQL_VALID_URI = '/gdc/md/%s/maqlvalidator'
    PULL_URI = '/gdc/md/%s/etl/pull'
    DML_EXEC_URI = '/gdc/md/%s/dml/manage'

    def __init__(self, connection):
        self.connection = connection

    def load(self, id=None, name=None):
        self.id = id or self.get_id_by_name(name)
        return self

    def get_id_by_name(self, name):
        """Retrieve the project identifier"""
        data = self.connection.get_metadata()
        for link in data['about']['links']:
            if link['title'] == name:
                logger.debug('Retrieved Project identifier for %s: %s' % (name, link['identifier']))
                return link['identifier']

        err_msg = 'Failed to retrieve Project identifier for %(project_name)s'
        raise ProjectNotFoundError(err_msg, links=data['about']['links'], project_name=name)

    def create(self, name, gd_token, desc=None, template_uri=None):
        """Create a new GoodData project"""
        request_data = {
            'project': {
                'meta': {
                    'title': name,
                    'summary': desc,
                },
                'content': {
                    'guidedNavigation': '1',
                    'authorizationToken': gd_token,
                },
            }
        }
        if template_uri:
            request_data['project']['meta']['projectTemplate'] = template_uri
        try:
            response = self.connection.post(self.PROJECTS_URI, request_data)
            response.raise_for_status()
        except HTTPError, err:
            try:
                err_msg = 'Could not create project (%(name)s), status code: %(status_code)s'
                raise ProjectCreationError(
                    err_msg, name=name, response=err.response.content,
                    status_code=err.response.status_code
                )
            except ValueError:
                raise GoodDataTotallyDown(err.response)
        else:
            id = response.json()['uri'].split('/')[-1]
            logger.debug("Created project name=%s with id=%s" % (name, id))
            return self.load(id=id)

    def delete(self):
        """Delete a GoodData project"""
        try:
            uri = '/'.join((self.PROJECTS_URI, self.id))
            self.connection.delete(uri=uri)
        except HTTPError, err:
            try:
                err_msg = 'Project does not seem to be opened: %(project_id)s'
                raise ProjectNotOpenedError(
                    err_msg, project_id=self.id, uri=uri,
                    status_code=err.response.status_code,
                    response=err.response.content
                )
            except ValueError:
                raise GoodDataTotallyDown(err.response)
        except TypeError:
            err_msg = 'Project does not seem to be opened: %(project_id)s'
            raise ProjectNotOpenedError(err_msg, project_id=self.id, uri=uri)

    def validate_maql(self, maql):
        """
        A function that uses the API entry point
        to validate the MAQL generated by the client.
        """
        if not maql:
            raise AttributeError('MAQL missing, nothing to execute')
        data = {'expression': maql}

        try:
            response = self.connection.post(uri=self.MAQL_VALID_URI % self.id, data=data)
            response.raise_for_status()
        except HTTPError, err:
            try:
                err_msg = 'Could not access to remote validator: %(status_code)s'
                raise MaqlValidationFailed(
                    err_msg, response=err.response.content,
                    status_code=err.response.status_code
                )
            except ValueError:
                raise GoodDataTotallyDown(err.response)
        else:
            # verify response content
            content = response.json()
            if 'maqlOK' not in content:
                err_msg = 'MAQL queries did not validate'
                raise MaqlValidationFailed(err_msg, reponse=content)

    def execute_maql(self, maql, wait_for_finish=True):
        self.validate_maql(maql)

        data = {'manage': {'maql': maql}}
        try:
            response = self.connection.post(uri=self.MAQL_EXEC_URI % self.id, data=data)
            response.raise_for_status()
        except HTTPError, err:
            try:
                err_json = err.response.json()['error']
                raise MaqlExecutionFailed(
                    get_api_msg(err_json), gd_error=err_json,
                    status_code=err.response.status_code, maql=maql
                )
            except ValueError:
                raise GoodDataTotallyDown(err.response)
        # It seems the API can retrieve several links
        task_uris = [entry['link'] for entry in response.json()['entries']]

        if wait_for_finish:
            for task_uri in task_uris:
                self.poll(task_uri, 'wTaskStatus.status', MaqlExecutionFailed, {'maql': maql})

    def execute_dml(self, maql):
        """
        Execute MAQL statements on the DML entrypoint of the API,
        for example deleting rows for a dataset, etc...

        :param maql:    the MAQL statements
        """
        data = {'manage': {'maql': maql}}

        try:
            response = self.connection.post(uri=self.DML_EXEC_URI % self.id, data=data)
            response.raise_for_status()
        except HTTPError, err:
            try:
                err_json = err.response.json()['error']
                raise DMLExecutionFailed(
                    get_api_msg(err_json), gd_error=err_json,
                    status_code=err.response.status_code, maql=maql
                )
            except ValueError:
                raise GoodDataTotallyDown(err.response)

        uri = response.json()['uri']
        self.poll(uri, 'taskState.status', DMLExecutionFailed, {'maql': maql})

    def integrate_uploaded_data(self, dir_name, wait_for_finish=True):
        try:
            response = self.connection.post(self.PULL_URI % self.id,
                                            {'pullIntegration': dir_name})
            response.raise_for_status()
        except HTTPError, err:
            try:
                status_code = err.response.status_code
                if status_code == 401:
                    self.connection.relogin()
                    response = self.connection.post(self.PULL_URI % self.id,
                                                    {'pullIntegration': dir_name})
                else:
                    err_json = err.response.json()['error']
                    raise UploadFailed(
                        get_api_msg(err_json), gd_error=err_json,
                        status_code=status_code, dir_name=dir_name
                    )
            except ValueError:
                raise GoodDataTotallyDown(err.response)

        task_uri = response.json()['pullTask']['uri']

        if wait_for_finish:
            self.poll(task_uri, 'taskStatus', UploadFailed, {'dir_name': dir_name})

    def poll(self, uri, status_field, ErrorClass, err_json=None):
        """
        This function is useful to poll a given uri. It looks
        at the `status_field` to know the status of the task.

        In case of failure, it will raise an error of the type
        ErrorClass, with an extra information defined by `err_json`.
        """
        while True:
            status = response = self.connection.get(uri=uri).json()

            for field in status_field.split('.'):
                status = status[field]
            logger.debug(status)
            if status == 'OK':
                break
            if status in ('ERROR', 'WARNING'):
                err_json = err_json or {}
                err_msg = 'An error occured while polling uri %(uri)s'
                raise ErrorClass(
                    err_msg, response=response,
                    custom_error=err_json, uri=uri
                )

            time.sleep(0.5)
