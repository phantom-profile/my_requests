## my_requests lib

Made as self educational project.

Main aim - is to implement http client from scratch 
without any external lib or high-level tools like urllib Request

### Code base
- my_requests.py - actual lib
- main.py - some examples of launching requests
- server.py - simple web server for localhost testing

### Features
- HTTP(s) 1.1 support
- handle timeouts
- logging
- redirects handling

### Things can be improved
- New socket for each request is inefficient
- New Client object for each request
- Cookies management not implemented
- More flexible client configuration
- Used urllib for building query string from dict. Need own implementation
