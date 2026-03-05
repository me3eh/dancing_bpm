from flask import Flask, render_template, request, jsonify
import os

app = Flask(__name__)
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "videos")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    f = request.files.get("video")
    if not f:
        return jsonify({"error": "no file"}), 400
    filename = f.filename.replace(" ", "_")
    path = os.path.join(UPLOAD_FOLDER, filename)
    f.save(path)
    return jsonify({"url": f"/static/videos/{filename}", "name": filename})

if __name__ == "__main__":
    # app.run(debug=True, port=5000) only use locally, without docker
    app.run(host="0.0.0.0", port=5000, debug=False)