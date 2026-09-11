from flask import Flask
app = Flask(__name__)

@app.route("/")
def title():
    return "<p>Convert files locally with using flux app.</p>"

def main():
    app.run()

if __name__ == "__main__":
    main()