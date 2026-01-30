# app.py
# Async Power Automate callback pattern using runId
# Payload per flow using explicit if-blocks

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import time
import datetime
import requests
from dotenv import load_dotenv

# -----------------------------
# Load environment
# -----------------------------
load_dotenv()

# -----------------------------
# Config
# -----------------------------
PA_CONNECT_TIMEOUT = 5
PA_READ_TIMEOUT = 10
TTL_SECONDS = 3600  # 1 hour

# In-memory runId -> status/result
request_status = {}

PRODUCT_FLOW_MAPPING = {
    "flow_01": "QR_PRODUCT_APPROVAL_FLOW_URL",
    "flow_02": "INSURANCE_CLAIM_FLOW_URL",
    "flow_03": "CUSTOMER_FEEDBACK_FLOW_URL",
    "flow_04": "RESUME_SCREEN_FLOW_URL",
    "flow_05": "INVOICE_PROCESSING_FLOW_URL",
    "flow_06": "WEB_PRICE_FLOW_URL",
    "flow_07": "LINKEDIN_FLOW_URL",
    "flow_13": "ID_CARD_FLOW_URL",
    "flow_14": "PRODUCT_WARRANTY_FLOW_URL",
    "flow_00": "TST_FLOW"
}

# -----------------------------
# App setup
# -----------------------------
app = Flask(__name__)
#CORS(app, resources={
#    r"/trigger-flow": {"origins": ["*"], "methods": ["POST"]},
#    r"/check-status": {"origins": ["*"], "methods": ["GET"]},
#   r"/flow-callback": {"origins": ["*"], "methods": ["POST"]}
#})

CORS(app, resources={
    r"/trigger-flow": {
        "origins": [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "https://unlimitedautomation.netlify.app",
            "*"               
        ],
        "methods": ["GET", "POST", "OPTIONS"],          
        "allow_headers": ["Content-Type", "Authorization"]
    },
    r"/check-status": {                                
        "origins": ["http://localhost:5173", "https://unlimitedautomation.netlify.app", "*"],
        "methods": ["GET", "OPTIONS"],
    },
    r"/flow-callback": {
        "origins": ["*"],                           
        "methods": ["POST", "OPTIONS"],
    }
})

# -----------------------------
# Helpers
# -----------------------------
def now_iso():
    return datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"

def cleanup_expired():
    now = time.time()
    expired = [k for k, v in request_status.items() if now - v.get("_ts", now) > TTL_SECONDS]
    for k in expired:
        request_status.pop(k, None)

def save_status(run_id, status, result=None, error=None):
    request_status[run_id] = {
        "runId": run_id,
        "status": status,
        "result": result,
        "error": error,
        "updatedAt": now_iso(),
        "_ts": time.time()
    }

def get_flow_url(product_id):
    env_key = PRODUCT_FLOW_MAPPING.get(product_id)
    return os.getenv(env_key) if env_key else None

# -----------------------------
# Routes
# -----------------------------
@app.route("/trigger-flow", methods=["POST"])
def trigger_flow():
    try:
        data = request.get_json(force=True)
        product_id = data.get("product_id")
        filename = data.get("filename")
        file_content = data.get("fileContent")

        if not product_id or product_id not in PRODUCT_FLOW_MAPPING:
            return jsonify({
                "success": False,
                "error": "Invalid product ID",
                "valid_products": list(PRODUCT_FLOW_MAPPING.keys())
            }), 400

        flow_url = get_flow_url(product_id)
        if not flow_url:
            return jsonify({
                "success": False,
                "error": f"Flow URL not configured for {product_id}"
            }), 500

        # Fix base64 padding
        if file_content and isinstance(file_content, str):
            padding = len(file_content) % 4
            if padding:
                file_content += "=" * (4 - padding)

        # Build payload exactly as your snippet
        payload = {
            "filename": filename,
            "fileContent": file_content
        }

        if product_id == "flow_02":
            payload["extraField1"] = data.get("extraField1")
            payload["extraField2"] = data.get("extraField2")
            payload["extraField3"] = data.get("extraField3")
        if product_id == "flow_05":
            payload["extraField4"] = data.get("extraField4")
        if product_id == "flow_06":
            payload["extraField5"] = data.get("extraField5")
            payload["extraField6"] = data.get("extraField6")
        if product_id == "flow_07":
            payload["extraField9"] = data.get("extraField9")
        if product_id == "flow_14":
            payload["extraField7"] = data.get("extraField7")
        if product_id == "flow_13":
            payload["extraField8"] = data.get("extraField8")

        # Add callback URL for async response
       # payload["callback_url"] = f"{os.getenv('BACKEND_URL')}/flow-callback"

        # Trigger Power Automate flow (long timeout)
        response = requests.post(flow_url, json=payload, timeout=1400)

        # Try to get runId from PA
        try:
            run_id = response.json().get("runId")
        except Exception:
            run_id = None

        if run_id:
            save_status(run_id, status="Running")

        return jsonify({
            "success": True,
            "filename": filename,
            "product_id": product_id,
            "runId": run_id,
            "status_code": response.status_code,
            "response": response.text
        }), 202

    except requests.exceptions.Timeout:
        return jsonify({
            "success": False,
            "error": "Request timed out",
            "product_id": product_id
        }), 504

    except requests.exceptions.RequestException as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "product_id": product_id
        }), 500

    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }), 500

@app.route("/flow-callback", methods=["POST"])
def flow_callback():
    try:
        body = request.get_json(force=True)
        run_id = body.get("runId")
        if not run_id:
            return jsonify({"error": "runId required"}), 400

        save_status(
            run_id=run_id,
            status=body.get("status"),
            result=body.get("result"),
            error=body.get("error")
        )

        cleanup_expired()
        return jsonify({"ok": True}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/check-status", methods=["GET"])
def check_status():
    run_id = request.args.get("runId")
    if not run_id:
        return jsonify({"error": "runId required"}), 400

    cleanup_expired()
    data = request_status.get(run_id)
    if not data:
        return jsonify({
            "runId": run_id,
            "status": "Pending",
            "result": None,
            "error": None
        }), 200

    return jsonify(data), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "time": now_iso()}), 200

# -----------------------------
# Run server
# -----------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)

