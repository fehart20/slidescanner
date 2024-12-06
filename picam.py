from flask import Flask, request, jsonify
import requests
import RPi.GPIO as GPIO
import time
import logging
import threading

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# Define the GPIO pin the relay is connected to
RELAY_PIN = 2

# Setup GPIO mode
GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_PIN, GPIO.OUT)
GPIO.output(RELAY_PIN, GPIO.LOW)  # Ensure relay is off at script start

# Flag to indicate if the system is currently capturing
is_capturing = threading.Lock()

def is_digicam_available(digi_cam_ip):
    test_url = f"http://{digi_cam_ip}:5513/?CMD=Ping"
    try:
        logging.info(f"Checking availability of DigiCamControl at {test_url}")
        response = requests.get(test_url, timeout=5)
        if response.status_code == 200:
            logging.info("DigiCamControl is available.")
            return True
        else:
            logging.warning(f"DigiCamControl returned unexpected status: {response.status_code}")
            return False
    except requests.RequestException as e:
        logging.error(f"Error checking DigiCamControl availability: {e}")
        return False

def advance_slide(digi_cam_ip, loops):
    for loop in range(0, int(loops)):
        logging.info(f"Advancing slide {loop + 1} of {loops}")

        # Activate the relay for 0.25 seconds to advance the projector
        logging.info("Setting GPIO HIGH to activate relay.")
        GPIO.output(RELAY_PIN, GPIO.HIGH)
        time.sleep(0.25)
        logging.info("Setting GPIO LOW to deactivate relay.")
        GPIO.output(RELAY_PIN, GPIO.LOW)

        # Wait for the projector to advance the slide
        time.sleep(1.5)

        # Trigger the camera capture via the DigiCamControl web service
        capture_url = f"http://{digi_cam_ip}:5513/?CMD=Capture"
        try:
            logging.info(f"Capturing image using DigiCamControl at {capture_url}")
            response = requests.post(capture_url)
            response.raise_for_status()
            logging.info("Image captured successfully.")
        except requests.RequestException as e:
            logging.error(f"Error capturing image: {e}")
            return f"Error capturing image: {e}", 500

        # Wait for the image to transfer from the camera to the computer
        time.sleep(2)

    logging.info("Slide capturing process completed.")
    return "Finished", 200

@app.route('/advance/<digi_cam_ip>/<int:loops>', methods=['GET'])
def advance(digi_cam_ip, loops):
    if is_capturing.locked():
        logging.warning("Request rejected: System is currently capturing.")
        return jsonify({"error": "System is currently capturing."}), 409

    if not is_digicam_available(digi_cam_ip):
        logging.error("Request rejected: DigiCamControl is not available.")
        return jsonify({"error": "DigiCamControl is not available."}), 503

    def capture_task():
        with is_capturing:
            advance_slide(digi_cam_ip, loops)

    logging.info("Starting capture thread.")
    threading.Thread(target=capture_task, daemon=True).start()
    return jsonify({"message": "Capture process started successfully.", "capture_count": loops, "digicamcontroler_ip": digi_cam_ip}), 200

if __name__ == "__main__":
    try:
        # Start the Flask app
        logging.info("Starting Flask app...")
        app.run(host="0.0.0.0", port=8080)
    finally:
        # Cleanup GPIO settings on exit
        logging.info("Cleaning up GPIO settings...")
        GPIO.cleanup()
