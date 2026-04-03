// Serial Receive 5 Floats and Send PWM to Motors
const int motorPins[5] = {18, 19, 21, 22, 23};
const int pwmChannels[5] = {0, 1, 2, 3, 4};
const int freq = 5000;
const int resolution = 8;
float inputVals[5];

void setup() {
  Serial.begin(115200);
  for (int i = 0; i < 5; i++) {
    ledcSetup(pwmChannels[i], freq, resolution);
    ledcAttachPin(motorPins[i], pwmChannels[i]);
  }
}

void loop() {
  if (Serial.available() >= sizeof(float) * 5) {
    Serial.readBytes((char*)inputVals, sizeof(float) * 5);

    for (int i = 0; i < 5; i++) {
      float value = constrain(inputVals[i], 0.0, 1.0);
      int duty = int(value * 255);
      ledcWrite(pwmChannels[i], duty);
    }
  }
}
