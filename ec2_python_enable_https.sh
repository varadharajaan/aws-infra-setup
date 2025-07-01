#!/bin/bash

# === Input arguments ===
PORT=$1
APP_NAME=$2

# === Paths ===
BASE_DIR="/home/ec2-user/flaskapps"
APP_DIR="$BASE_DIR/$APP_NAME"
CERT_DIR="$APP_DIR/cert"
APP_FILE="$APP_DIR/app.py"
IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)

# === Create directories ===
mkdir -p "$CERT_DIR"
mkdir -p "$APP_DIR"

# === Generate self-signed certificate for this app ===
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$CERT_DIR/key.pem" -out "$CERT_DIR/cert.pem" -days 365 \
  -subj "/CN=$IP"

# === Create the Flask app file ===
cat <<EOF > "$APP_FILE"
from flask import Flask
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ Hello from $APP_NAME running on port $PORT (HTTPS)"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=$PORT, ssl_context=("$CERT_DIR/cert.pem", "$CERT_DIR/key.pem"))
EOF

echo "✅ App $APP_NAME created at $APP_FILE"
echo "👉 To run the app:"
echo "    python3 $APP_FILE"
echo "👉 Then access it at: https://$IP:$PORT"


# Deploy apps
#./deploy-flask-app.sh 5000 analytics
#./deploy-flask-app.sh 5001 payments
#./deploy-flask-app.sh 5002 dashboard