from wsgiref.simple_server import make_server, WSGIServer
from socketserver import ThreadingMixIn
from time import sleep

# Every WSGI application must have an application object - a callable
# object that accepts two arguments. For that purpose, we're going to
# use a function (note that you're not limited to a function, you can
# use a class for example). The first argument passed to the function
# is a dictionary containing CGI-style environment variables and the
# second variable is the callable object.
def simple_app(environ, start_response):
    status = '200 OK'  # HTTP Status
    headers = [('Content-type', 'text/plain; charset=utf-8')]  # HTTP Headers
    start_response(status, headers)

    try:
        request_body_size = int(environ['CONTENT_LENGTH'])
        request_body = environ['wsgi.input'].read(request_body_size)
    except (TypeError, ValueError):
        request_body = "0"
    try:
        response_body = str(request_body)
    except:
        response_body = "error"
    print(response_body)
    return [b"hello"] 

class ThreadingWSGIServer(ThreadingMixIn, WSGIServer): 
        pass

httpd = make_server('', 9060, simple_app, ThreadingWSGIServer)
print('Listening on port 9060....')
httpd.serve_forever()
"""
with make_server('', 9060, hello_world_app) as httpd:
    print("Serving on port 9060...")

    # Serve until process is killed
    httpd.serve_forever()
"""
