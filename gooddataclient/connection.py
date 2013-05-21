import os
import logging

import simplejson as json
import requests
from requests.exceptions import (
    HTTPError, ConnectionError
)

from gooddataclient.exceptions import (
    AuthenticationError, GoodDataTotallyDown, GoodDataClientError, get_api_msg
)
from gooddataclient.archiver import create_archive, DEFAULT_ARCHIVE_NAME

logger = logging.getLogger("gooddataclient")

JSON_HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json'
}


class Connection(object):

    HOST = 'https://secure.gooddata.com'

    LOGIN_URI = '/gdc/account/login'
    TOKEN_URI = '/gdc/account/token'
    MD_URI = '/gdc/md/'

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.webdav = Webdav(username, password)
        self.login(username, password)

    def login(self, username, password):
        data = {
            'postUserLogin': {
                'login': username,
                'password': password,
                'remember': 1,
            }
        }
        r1 = self.post(uri=self.LOGIN_URI, data=data, login=True,
                       raise_cls=AuthenticationError)
        self.cookies = self.webdav.cookies = r1.cookies
        self.get(uri=self.TOKEN_URI, raise_cls=AuthenticationError)

    def relogin(self):
        self.login(self.username, self.password)

    def get(self, uri, raise_cls=GoodDataClientError, err_msg=None, **kwargs):
        logger.debug('GET: %s' % uri)
        get_data = {
            'url': self.HOST + uri,
            'cookies': self.cookies,
            'headers': JSON_HEADERS,
            'auth': (self.username, self.password)
        }
        return self.call('get', get_data, raise_cls, err_msg, **kwargs)

    def post(self, uri, data, headers=JSON_HEADERS, login=False,
             raise_cls=GoodDataClientError, err_msg=None, **kwargs):
        logger.debug('POST: %s' % uri)
        post_data = {
            'url': self.HOST + uri,
            'data': json.dumps(data),
            'headers': headers,
            'auth': (self.username, self.password)
        }
        if not login:
            post_data['cookies'] = self.cookies

        return self.call('post', post_data, raise_cls, err_msg, **kwargs)


    def call(self, call_method, call_arguments, raise_cls, err_msg, **err_arguments):
        try:
            get_or_post = getattr(requests, call_method)
            response = get_or_post(**call_arguments)
            response.raise_for_status()
        except HTTPError, err:
            if not err_msg:
                try:
                    err_msg = get_api_msg(err.response.json()['error'])
                except (ValueError, KeyError):
                    err_msg = err.response
            raise raise_cls(
                err_msg, status_code=err.response.status_code,
                **err_arguments
            )
        except ConnectionError, err:
            raise GoodDataTotallyDown(err.message)
        return response

    def delete(self, uri):
        logger.debug('DELETE: %s' % uri)
        r = requests.delete(url=self.HOST + uri, auth=(self.username, self.password))
        r.raise_for_status()
        return r

    def get_metadata(self):
        return self.get(self.MD_URI).json()


class Webdav(Connection):

    HOST = 'https://secure-di.gooddata.com'
    UPLOADS_URI = '/uploads/%s/'

    def __init__(self, username, password):
        self.username = username
        self.password = password

    def upload(
        self, data, sli_manifest, dates=[], datetimes=[],
        keep_csv=False, csv_file=None, no_upload=False
    ):
        '''Create zip file with data in csv format and manifest file, then create
        directory in webdav and upload the zip file there.

        @param data: csv data to upload
        @param sli_manifest: dictionary with the columns definitions
        @param dates: list of date fields
        @param datetimes: lits of datetime fields
        @param keep_csv: keep csv file on filesystem
        @param csv_file: abspath where to keep csv file
        @param no_upload: do the upload or not

        return the name of the temporary file, hence the name of the directory
        created in webdav uploads folder
        '''
        archive = create_archive(
            data, sli_manifest, dates,
            datetimes, keep_csv, csv_file
        )
        if no_upload:
            os.remove(archive)
            return csv_file

        dir_name = os.path.basename(archive)
        # create the folder on WebDav
        self.mkcol(uri=self.UPLOADS_URI % dir_name)
        # open the files to read them
        f_archive = open(archive, 'rb')

        # upload the files to WebDav
        archive_uri = ''.join((self.UPLOADS_URI % dir_name, DEFAULT_ARCHIVE_NAME))
        self.put(uri=archive_uri, data=f_archive.read(),
                 headers={'Content-Type': 'application/zip'})

        # close and remove the files
        f_archive.close()
        os.remove(archive)

        return dir_name

    def mkcol(self, uri):
        logger.debug('MKCOL: %s' % uri)
        r = requests.request(method='MKCOL', url=self.HOST + uri, auth=(self.username, self.password))
        r.raise_for_status()

    def put(self, uri, data, headers):
        logger.debug('PUT: %s' % uri)
        r = requests.put(url=self.HOST + uri, data=data, headers=headers, auth=(self.username, self.password))
        r.raise_for_status()

    def delete(self, dir_name):
        uri = self.UPLOADS_URI % dir_name
        super(Webdav, self).delete(uri=uri)
