// Southbank flood prototype: two float switches, JSON lines v1 over USB serial.
// Preserves the supplied circuit: D2/D3 INPUT_PULLUP, HIGH = raised/wet;
// LEDs D7/D8. Confirm switch polarity on the actual installation.
const int floatSwitch1 = 2;
const int floatSwitch2 = 3;
const int led1 = 7;
const int led2 = 8;
const unsigned long debounceTime = 100;
const unsigned long heartbeatTime = 1000;

bool previousReading1;
bool previousReading2;
bool switch1State;
bool switch2State;
unsigned long switch1ChangeTime = 0;
unsigned long switch2ChangeTime = 0;
unsigned long lastSentAt = 0;
unsigned long sequence = 0;
int previousFloodLevel = -2; // Ensures the initial INVALID state is sent too.
bool initialSent = false;

void sendReading(int level, unsigned long now) {
  Serial.print(F("{\"type\":\"flood_reading\",\"protocolVersion\":1,\"sequence\":"));
  Serial.print(sequence++);
  Serial.print(F(",\"uptimeMs\":"));
  Serial.print(now);
  Serial.print(F(",\"lowerFloat\":"));
  Serial.print(switch1State ? F("true") : F("false"));
  Serial.print(F(",\"upperFloat\":"));
  Serial.print(switch2State ? F("true") : F("false"));
  Serial.print(F(",\"floodLevel\":"));
  Serial.print(level);
  Serial.println(F("}"));
}

void setup() {
  pinMode(floatSwitch1, INPUT_PULLUP);
  pinMode(floatSwitch2, INPUT_PULLUP);
  pinMode(led1, OUTPUT);
  pinMode(led2, OUTPUT);
  Serial.begin(9600);
  previousReading1 = switch1State = digitalRead(floatSwitch1);
  previousReading2 = switch2State = digitalRead(floatSwitch2);
  switch1ChangeTime = switch2ChangeTime = millis();
}

void loop() {
  const unsigned long now = millis();
  const bool reading1 = digitalRead(floatSwitch1);
  const bool reading2 = digitalRead(floatSwitch2);
  if (reading1 != previousReading1) {
    switch1ChangeTime = now;
    previousReading1 = reading1;
  }
  if (reading2 != previousReading2) {
    switch2ChangeTime = now;
    previousReading2 = reading2;
  }
  // Unsigned subtraction is safe across the millis() uint32 wrap.
  if (now - switch1ChangeTime >= debounceTime) switch1State = reading1;
  if (now - switch2ChangeTime >= debounceTime) switch2State = reading2;
  // Wait for both inputs to settle before the first observation.
  if (!initialSent && (now - switch1ChangeTime < debounceTime || now - switch2ChangeTime < debounceTime)) return;

  int floodLevel;
  if (!switch1State && !switch2State) floodLevel = 0;
  else if (switch1State && !switch2State) floodLevel = 1;
  else if (switch1State && switch2State) floodLevel = 2;
  else floodLevel = -1;
  digitalWrite(led1, floodLevel == 1 || floodLevel == 2 ? HIGH : LOW);
  digitalWrite(led2, floodLevel == 2 ? HIGH : LOW);

  if (!initialSent || floodLevel != previousFloodLevel || now - lastSentAt >= heartbeatTime) {
    sendReading(floodLevel, now);
    previousFloodLevel = floodLevel;
    lastSentAt = now;
    initialSent = true;
  }
}
