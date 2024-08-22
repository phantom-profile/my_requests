import my_requests


def main():
    # using default configuration
    my_requests.post('https://echo-http-requests.appspot.com/echo', query={"param": "value"}, body={"a": 1})
    my_requests.get('http://echo-http-requests.appspot.com/echo', query={"param": "value"})
    my_requests.post('http://127.0.0.1:5000/redirect', query={"param": "value"}, body={"list": [1, 2, 3]})

    # using shared session
    session = my_requests.Session(timeout=15, headers={"Authorization": "Token 123-123"})
    session.post('http://127.0.0.1:5000/echo', query={"param": "value"}, body={"dict": {"key": "value"}})


if __name__ == '__main__':
    main()
