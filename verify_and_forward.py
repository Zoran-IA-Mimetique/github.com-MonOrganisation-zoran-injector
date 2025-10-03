#!/usr/bin/env python3
from flask import Flask, request, jsonify
import hashlib, requests, os, json, time

GITHUB_RAW_SHA_URL = "https://raw.githubusercontent.com/Zoran-IA-Mimetique/github.com-MonOrganisation-zoran-injector/main/injectors/zoran_gomg.sha512"
ETHICAL_THRESHOLD = 80
HUMAN_REVIEW_WEBHOOK = os.getenv("HUMAN_REVIEW_WEBHOOK")
MODEL_FORWARD_URL = os.getenv("MODEL_FORWARD_URL")
ATTESTATION_SIGNER_URL = os.getenv("ATTESTATION_SIGNER_URL")

app = Flask(__name__)

def sha512_of_text(txt: str) -> str:
    return hashlib.sha512(txt.encode('utf-8')).hexdigest()

def fetch_canonical_sha():
    r = requests.get(GITHUB_RAW_SHA_URL, timeout=5)
    r.raise_for_status()
    return r.text.strip()

def create_artifact(prompt, metadata):
    artifact = {
        "id": f"artifact-{int(time.time())}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "prompt_sample": prompt[:1000],
        "metadata": metadata
    }
    path = f"/tmp/{artifact['id']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, ensure_ascii=False, indent=2)
    return artifact, path

@app.route("/verify_and_forward", methods=["POST"])
def verify_and_forward():
    payload = request.get_json(force=True)
    prompt = payload.get("prompt", "")
    metadata = payload.get("metadata", {})

    computed = sha512_of_text(prompt)
    try:
        canonical = fetch_canonical_sha()
    except Exception as e:
        return jsonify({"ok": False, "reason": "cannot_fetch_canonical", "detail": str(e)}), 500

    if computed != canonical:
        return jsonify({"ok": False, "status": "mismatch", "computed_sha": computed, "canonical_sha": canonical}), 403

    eth_val = metadata.get("ethique_val")
    if eth_val is None:
        artifact, path = create_artifact(prompt, metadata)
        return jsonify({"ok": False, "status": "escalated", "artifact_id": artifact["id"]}), 202

    try:
        eth_val = float(eth_val)
    except:
        eth_val = 0.0

    if eth_val < ETHICAL_THRESHOLD:
        artifact, path = create_artifact(prompt, metadata)
        return jsonify({"ok": False, "status": "escalated", "artifact_id": artifact["id"]}), 202

    attestation = None
    if ATTESTATION_SIGNER_URL:
        try:
            r = requests.post(ATTESTATION_SIGNER_URL, json={"sha": computed, "metadata": metadata}, timeout=5)
            r.raise_for_status()
            attestation = r.json().get("attestation")
        except Exception:
            attestation = None

    if MODEL_FORWARD_URL:
        headers = {}
        if attestation:
            headers["X-Attestation"] = attestation
        try:
            r = requests.post(MODEL_FORWARD_URL, json={"prompt": prompt, "metadata": metadata}, headers=headers, timeout=30)
            return jsonify({"ok": True, "status": "forwarded", "model_response": r.json()}), r.status_code
        except Exception as e:
            return jsonify({"ok": False, "status": "forward_failed", "detail": str(e)}), 502

    return jsonify({"ok": True, "status": "verified", "sha": computed, "attestation": attestation}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
