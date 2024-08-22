import dataclasses
import enum
import json
import logging
import socket
import ssl
import sys
import urllib.parse
from typing import Any

ENCODING = 'utf-8'
SEP = "\r\n"

JsonType = dict[str, str | dict | list | int | None]


class Methods(enum.StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    HEAD = "HEAD"


@dataclasses.dataclass(kw_only=True)
class ParsedUrl:
    class InvalidUrlError(Exception):
        pass

    PORTS = {
        'http': 80,
        'https': 443
    }
    PROTOCOL_SEP = '://'

    url: str
    protocol: str = ''
    host: str = ''
    port: int = 80
    path: str = ''

    @classmethod
    def is_relative(cls, url):
        return cls.PROTOCOL_SEP not in url

    def __post_init__(self):
        try:
            self._parse()
        except Exception as e:
            raise self.InvalidUrlError(f"url '{self.url}' is invalid. \nOriginal exception was {repr(e)}")

    def is_secure(self) -> bool:
        return self.protocol == 'https'

    def _parse(self):
        self.protocol, url = self.url.split(self.PROTOCOL_SEP)
        host = url.split('/')[0]
        try:
            self.port = int(host.split(':')[1])
        except IndexError:
            self.port = self.PORTS[self.protocol]
        self.host = host.split(':')[0]
        self.path = url.lstrip(host)


@dataclasses.dataclass(kw_only=True)
class Request:
    DEFAULT_HEADERS = {
        "Accept": "*/*",
        "User-Agent": "CustomClient/1.0",
        "Connection": "close"
    }

    method: Methods
    url: ParsedUrl
    query: dict[str, str] = dataclasses.field(default_factory=dict)
    headers: dict[str, str] = dataclasses.field(default_factory=dict)
    body: dict[str, Any] = dataclasses.field(default_factory=dict)
    built_request: str = ""

    def __post_init__(self):
        if self.method not in Methods:
            raise AttributeError("Method is not allowed")

        self.headers = {**self.DEFAULT_HEADERS, "Host": self.url.host, **self.headers}
        if self.body:
            self.headers["Content-Length"] = str(len(self.json()))
            self.headers["Content-Type"] = "application/json"

    def raw(self, encode=False):
        if self.built_request:
            return self.built_request.encode(ENCODING) if encode else self.built_request

        query = self.build_query()
        headers = self.build_headers()
        parts = [f"{self.method} {self.url.path + query} HTTP/1.1", headers, self.json()]
        self.built_request = SEP.join(parts)
        return self.built_request.encode(ENCODING) if encode else self.built_request

    def build_query(self):
        query_string = "" if not self.query else f"?{urllib.parse.urlencode(self.query)}"
        return query_string

    def build_headers(self):
        headers_string = ""
        for name, value in self.headers.items():
            headers_string += f"{name}: {value}\r\n"
        return headers_string

    def json(self):
        return json.dumps(self.body) if self.body else ""


@dataclasses.dataclass
class Response:
    class JsonParseError(Exception):
        pass

    raw: str
    status: int = 200
    body: str = ''
    headers: dict[str, str] = dataclasses.field(default_factory=dict)

    def __post_init__(self):
        self._parse()

    def json(self) -> JsonType:
        try:
            return json.loads(self.body)
        except json.JSONDecodeError:
            raise self.JsonParseError(f"cannot deserialize '{self.body}'")

    def is_success(self):
        return str(self.status).startswith('2')

    def is_redirect(self):
        return str(self.status).startswith('3')

    def _parse(self):
        strings = self.raw.split(SEP)
        self._fetch_status(strings[0])
        self._fetch_headers(strings[1:])
        self._fetch_body(strings[-1])

    def _fetch_status(self, status_string):
        self.status = int(status_string.split()[1])

    def _fetch_body(self, raw: str):
        length = int(self.headers['Content-Length'])
        self.body = raw[:length]

    def _fetch_headers(self, headers: list[str]):
        for header in headers:
            if not header:
                break
            name, value = header.split(': ')
            self.headers[name] = value

    def __str__(self):
        return f'Response(status={self.status}, body="{repr(self.body)}", headers={self.headers})'


class SocketWrapper:
    RESPONSE_SIZE = 256 * 1024
    DEFAULT_TIMEOUT = 30  # seconds

    class RequestTimeoutError(Exception):
        pass

    def __init__(self, host: str, port: int, timeout: float = DEFAULT_TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.server_address = (self.host, self.port)
        self.socket = None

    def request(self, raw_data: bytes):
        try:
            self.refresh_socket()
            self.socket.sendall(raw_data)
            return self.receive_full_response()
        except TimeoutError:
            raise self.RequestTimeoutError(f"Request timed out in {self.timeout} seconds")
        finally:
            self.socket.close()

    def refresh_socket(self):
        self.socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM)
        self.socket.settimeout(self.timeout)
        self.socket.connect(self.server_address)
        if self.port == ParsedUrl.PORTS['https']:
            context = ssl.create_default_context()
            self.socket = context.wrap_socket(self.socket, server_hostname=self.host)

    def receive_full_response(self):
        buffer = []
        part = self.socket.recv(self.RESPONSE_SIZE)
        while part:
            buffer.append(part)
            part = self.socket.recv(self.RESPONSE_SIZE)
        return b''.join(buffer).decode(ENCODING)


class Client:
    MAX_REDIRECTS = 5

    def __init__(self, url: ParsedUrl, timeout: int, logger: 'SessionLogger'):
        self.url = url
        self.timeout = timeout
        self.logger = logger

    def make_request(self, method: Methods, **kwargs) -> Response:
        request = Request(url=self.url, method=method, **kwargs)
        response = self._request(request)
        if response.is_redirect():
            response = self._handle_redirect(response, **kwargs)
        return response

    def _handle_redirect(self, response: Response, **kwargs):
        redirects = 1
        while response.is_redirect():
            if redirects > self.MAX_REDIRECTS:
                raise RuntimeError(f"Maximum {self.MAX_REDIRECTS} redirects count reached")
            location = response.headers.get('Location')
            if not location:
                return response
            if ParsedUrl.is_relative(location):
                self.url.path = location
                request = Request(url=self.url, method=Methods.GET, **kwargs)
            else:
                url = ParsedUrl(location)
                request = Request(url=url, method=Methods.GET, **kwargs)
            response = self._request(request)
            redirects += 1
        return response

    def _request(self, request: Request):
        self.logger.info(request.raw(), action_name='request')
        data = self._socket_wrapper.request(request.raw(encode=True))
        response = Response(raw=data)
        self.logger.info(str(response), action_name="response")
        return response

    @property
    def _socket_wrapper(self):
        return SocketWrapper(self.url.host, self.url.port, self.timeout)


class SessionLogger:
    def __init__(self, name: str = 'my_requests', dst: str = None, level: int = logging.INFO):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        self.logger.handlers = []
        handler = logging.FileHandler(dst) if dst else logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s: %(message)s')
        handler.setFormatter(formatter)

        self.logger.addHandler(handler)
        self.logger.setLevel(level)

    def set_handler(self, handler: logging.Handler):
        self.logger.handlers = []
        self.logger.addHandler(handler)

    def set_formatter(self, formatter: logging.Formatter):
        self.logger.handlers[0].setFormatter(formatter)

    def info(self, msg: str, action_name: str = ''):
        if action_name:
            self.logger.info(f"Performing {action_name} action: ")
        self.logger.info(msg)


class Session:
    def __init__(self, **config):
        self.logger = config.get('logger', SessionLogger())
        self.timeout = config.get('timeout', SocketWrapper.DEFAULT_TIMEOUT)
        self.headers = config.get('headers', {})
        self.url: ParsedUrl | None = None

    def get(self, url: str, query: JsonType = None, headers: JsonType = None) -> Response:
        self.url = ParsedUrl(url=url)
        return self._new_client().make_request(
            Methods.GET,
            **self._prepare_kwargs(query=query, headers=headers)
        )

    def post(self, url: str, query: JsonType = None, headers: JsonType = None, body: JsonType = None) -> Response:
        self.url = ParsedUrl(url=url)
        return self._new_client().make_request(
            Methods.POST,
            **self._prepare_kwargs(query=query, headers=headers, body=body)
        )

    def put(self, url: str, query: JsonType = None, headers: JsonType = None, body: JsonType = None) -> Response:
        self.url = ParsedUrl(url=url)
        return self._new_client().make_request(
            Methods.PUT,
            **self._prepare_kwargs(query=query, headers=headers, body=body)
        )

    def patch(self, url: str, query: JsonType = None, headers: JsonType = None, body: JsonType = None) -> Response:
        return self.put(url, query=query, headers=headers, body=body)

    def delete(self, url: str, query: JsonType = None, headers: JsonType = None):
        self.url = ParsedUrl(url=url)
        return self._new_client().make_request(
            Methods.DELETE,
            **self._prepare_kwargs(query=query, headers=headers)
        )

    def _prepare_kwargs(self, **kwargs):
        kwargs['headers'] = self.headers | (kwargs.get('headers') or {}) or None
        return self._compact(**kwargs)

    def _new_client(self):
        return Client(url=self.url, timeout=self.timeout, logger=self.logger)

    @staticmethod
    def _compact(**pairs):
        new = {}
        for key, value in pairs.items():
            if value is not None:
                new[key] = value
        return new


def get(url: str, query: JsonType = None, headers: JsonType = None) -> Response:
    return Session().get(url, query=query, headers=headers)


def post(url: str, query: JsonType = None, headers: JsonType = None, body: JsonType = None) -> Response:
    return Session().post(url, query=query, headers=headers, body=body)


def put(url: str, query: JsonType = None, headers: JsonType = None, body: JsonType = None) -> Response:
    return Session().put(url, query=query, headers=headers, body=body)


def delete(url: str, query: JsonType = None, headers: JsonType = None) -> Response:
    return Session().delete(url, query=query, headers=headers)
