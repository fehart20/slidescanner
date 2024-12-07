from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
import requests
import RPi.GPIO as GPIO
import time
import logging
import threading


# Flask and SocketIO setup
app = Flask(__name__)
# Allow CORS for frontend communication
socketio = SocketIO(app, cors_allowed_origins="*")

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Define GPIO setup
RELAY_PIN = 2
GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_PIN, GPIO.OUT)
GPIO.output(RELAY_PIN, GPIO.HIGH)

# Flag and event for process management
is_capturing = threading.Lock()
abort_event = threading.Event()


def is_digicam_available(digi_cam_ip):
    test_url = f"http://{digi_cam_ip}:5513/?CMD=Ping"
    try:
        logging.info(f"Checking DigiCamControl availability at {test_url}")
        response = requests.get(test_url, timeout=5)
        return response.status_code == 200
    except requests.RequestException as e:
        logging.error(f"DigiCamControl availability check failed: {e}")
        return False


def advance_slide(digi_cam_ip, loops):
    total_loops = int(loops)
    for loop in range(total_loops):
        if abort_event.is_set():
            logging.warning("Slide advancement aborted.")
            socketio.emit('task_status', {'status': 'aborted'})
            return

        logging.info(f"Advancing slide {loop + 1} of {total_loops}")
        GPIO.output(RELAY_PIN, GPIO.LOW)
        time.sleep(0.25)
        GPIO.output(RELAY_PIN, GPIO.HIGH)

        # Emit progress update
        socketio.emit('progress_update', {
            'status': 'in_progress',
            'current_slide': loop + 1,
            'total_slides': total_loops
        })

        time.sleep(1.5)

        # Capture the image
        capture_url = f"http://{digi_cam_ip}:5513/?CMD=Capture"
        try:
            response = requests.post(capture_url)
            response.raise_for_status()
            logging.info("Image captured successfully.")
        except requests.RequestException as e:
            logging.error(f"Capture failed: {e}")
            socketio.emit('task_status', {
                          'status': 'error', 'message': str(e)})
            return

        time.sleep(2)

    logging.info("Slide advancement completed.")
    socketio.emit('task_status', {'status': 'completed'})


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/advance/<digi_cam_ip>/<int:loops>', methods=['GET'])
def advance(digi_cam_ip, loops):
    if is_capturing.locked():
        return jsonify({"error": "System is currently capturing."}), 409

    if not is_digicam_available(digi_cam_ip):
        return jsonify({"error": "DigiCamControl is not available."}), 503

    abort_event.clear()

    def capture_task():
        with is_capturing:
            advance_slide(digi_cam_ip, loops)

    threading.Thread(target=capture_task, daemon=True).start()
    return jsonify({"message": "Capture process started successfully."}), 200


@app.route('/abort', methods=['POST'])
def abort():
    if is_capturing.locked():
        abort_event.set()
        return jsonify({"message": "Capture process aborted successfully."}), 200
    return jsonify({"error": "No process to abort."}), 400


@app.route('/slide-back', methods=['POST'])
def slide_back():
    if is_capturing.locked():
        return jsonify({"error": "System is currently capturing."}), 409

    GPIO.output(RELAY_PIN, GPIO.LOW)
    time.sleep(0.75)
    GPIO.output(RELAY_PIN, GPIO.HIGH)
    return jsonify({"message": "Slide moved backward successfully."}), 200

@socketio.on('ping_server')
def handle_ping():
    emit('pong', {'timestamp': time.time()})


if __name__ == "__main__":
    try:
        logging.info("Starting Flask app...")
        socketio.run(app, host="0.0.0.0", port=8080)
    finally:
        logging.info("Cleaning up GPIO settings...")
        GPIO.cleanup()
