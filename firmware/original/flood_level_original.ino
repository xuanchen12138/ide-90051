// ----------------------------------------------------
// FLOOD LEVEL DETECTION SYSTEM
//
// LED 1 -> Pin 7
// LED 2 -> Pin 8
//
// HIGH = float raised / water detected
// LOW  = float hanging down / no water detected
// ----------------------------------------------------


// -------------------------
// Pin definitions
// -------------------------

const int floatSwitch1 = 2;
const int floatSwitch2 = 3;

const int led1 = 7;
const int led2 = 8;


// -------------------------
// Timing settings
// -------------------------

// A reading must remain unchanged for 100 ms
// before it is accepted as a real state change.

const unsigned long debounceTime = 100;


// -------------------------
// Variables
// -------------------------

// Current raw readings from the switches
bool reading1;
bool reading2;

// Previous raw readings
bool previousReading1;
bool previousReading2;

// Confirmed switch states after debouncing
bool switch1State;
bool switch2State;

// Time at which a raw switch change was first detected
unsigned long switch1ChangeTime = 0;
unsigned long switch2ChangeTime = 0;

// Current flood level
int floodLevel = 0;

// Previous flood level
int previousFloodLevel = -1;


// ----------------------------------------------------
// SETUP
// ----------------------------------------------------

void setup() {

  // Enable Arduino internal pull-up resistors
  pinMode(floatSwitch1, INPUT_PULLUP);
  pinMode(floatSwitch2, INPUT_PULLUP);

  // LEDs
  pinMode(led1, OUTPUT);
  pinMode(led2, OUTPUT);

  Serial.begin(9600);

  previousReading1 = digitalRead(floatSwitch1);
  previousReading2 = digitalRead(floatSwitch2);

  switch1State = previousReading1;
  switch2State = previousReading2;

  Serial.println("Flood monitoring system started");
}


// ----------------------------------------------------
// MAIN LOOP
// ----------------------------------------------------

void loop() {

  // ==================================================
  // 1. READ BOTH FLOAT SWITCHES
  // ==================================================

  reading1 = digitalRead(floatSwitch1);
  reading2 = digitalRead(floatSwitch2);


  // ==================================================
  // 2. FLOAT SWITCH 1 DEBOUNCE
  // ==================================================

  // Detect when the raw reading changes
  if (reading1 != previousReading1) {

    switch1ChangeTime = millis();

    previousReading1 = reading1;
  }

  // Only accept the new state if it has remained
  // unchanged for at least 100 ms
  if ((millis() - switch1ChangeTime >= debounceTime) &&
      (switch1State != reading1)) {

    switch1State = reading1;

    Serial.print("Lower float changed after ");
    Serial.print(millis() - switch1ChangeTime);
    Serial.println(" ms");
  }


  // ==================================================
  // 3. FLOAT SWITCH 2 DEBOUNCE
  // ==================================================

  if (reading2 != previousReading2) {

    switch2ChangeTime = millis();

    previousReading2 = reading2;
  }

  if ((millis() - switch2ChangeTime >= debounceTime) &&
      (switch2State != reading2)) {

    switch2State = reading2;

    Serial.print("Upper float changed after ");
    Serial.print(millis() - switch2ChangeTime);
    Serial.println(" ms");
  }


  // ==================================================
  // 4. DETERMINE FLOOD LEVEL
  // ==================================================

  if (switch1State == LOW &&
      switch2State == LOW) {

    floodLevel = 0;
  }

  // Flood Level 1
  else if (switch1State == HIGH &&
           switch2State == LOW) {

    floodLevel = 1;
  }

  // Flood Level 2
  else if (switch1State == HIGH &&
           switch2State == HIGH) {

    floodLevel = 2;
  }

  // Sensor Error
  else {

    floodLevel = -1;
  }


  // ==================================================
  // 5. UPDATE LEDs
  // ==================================================

  if (floodLevel == 0) {

    digitalWrite(led1, LOW);
    digitalWrite(led2, LOW);
  }

  else if (floodLevel == 1) {

    digitalWrite(led1, HIGH);
    digitalWrite(led2, LOW);
  }

  else if (floodLevel == 2) {

    digitalWrite(led1, HIGH);
    digitalWrite(led2, HIGH);
  }

  else {

    // Invalid state
    digitalWrite(led1, LOW);
    digitalWrite(led2, LOW);
  }


  // ==================================================
  // 6. ONLY SEND DATA WHEN FLOOD LEVEL CHANGES
  // ==================================================

  if (floodLevel != previousFloodLevel) {

    Serial.print("Flood level changed to: ");

    if (floodLevel == 0) {
      Serial.println("LEVEL 0");
    }

    else if (floodLevel == 1) {
      Serial.println("LEVEL 1");
    }

    else if (floodLevel == 2) {
      Serial.println("LEVEL 2");
    }

    else {
      Serial.println("INVALID SENSOR STATE");
    }


    // -----------------------------------------------
    // WEBSITE DATA TRANSMISSION
    // -----------------------------------------------
    //
    // Website Communication Will Go Here
    // 
    // -----------------------------------------------


    previousFloodLevel = floodLevel;
  }
} 