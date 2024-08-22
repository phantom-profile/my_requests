from flask import Flask, jsonify, redirect, request, url_for

app = Flask(__name__)


@app.route('/', methods=['GET'])
def home():
    return f"Welcome to the Basic HTTP Server with params {request.args}", 200


@app.route('/echo', methods=['POST'])
def echo():
    data = request.json
    return jsonify({"Body": data, "Query": request.args}), 200


@app.route('/redirect', methods=['POST'])
def redirect_post():
    return redirect(url_for('status'), code=301)


@app.route('/greet/<name>', methods=['GET'])
def greet(name):
    return f"Hello, {name}!", 200


@app.route('/status', methods=['GET'])
def status():
    return jsonify({"status": "Server is running"}), 200


if __name__ == '__main__':
    app.run(port=5000, debug=True)
