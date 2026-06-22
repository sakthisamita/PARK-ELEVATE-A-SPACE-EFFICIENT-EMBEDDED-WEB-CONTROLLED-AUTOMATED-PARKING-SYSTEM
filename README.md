# PARK-ELEVATE-A-SPACE-EFFICIENT-EMBEDDED-WEB-CONTROLLED-AUTOMATED-PARKING-SYSTEM

This project is a space-efficient parking solution that utilizes a vertical carousel mechanism to store vehicles. By stacking four parking slots (A, B, C, and D) vertically, the system minimizes ground space. Controlled by a web interface and a DC gear motor, the system automates the positioning of slots for seamless vehicle entry and exit.

**HARDWARE ARCHITECTURE**
The hardware revolves around a "Giant Wheel" structure driven by a DC Gear Motor.
- Rotational Logic: The system operates on a 90-degree indexing logic. Each 90-degree turn shifts the position of the slots.
- The "Ground" Level: At any given time, two slots are accessible at the bottom: Entry Side - Where the user loads their vehicle and Exit Side - Where the user retrieves their vehicle. 
- Slot Management: The hardware tracks the real-time position of slots A, B, C, and D. It calculates the shortest number of 90-degree rotations required to bring a specific slot to the Entry or Exit point.

**SOFTWARE ARCHITECTURE**
The system is managed via a web application that acts as the bridge between the user and the mechanical hardware.
- Authentication: Each user has a unique username and password.
- Session Logic: Selection (User chooses Entry or Exit), Availability Check (If "Entry" is selected but all four slots are occupied, the system displays a "Parking Full" notification, bypassing the login screen) and Validation (Users must log in to initiate any mechanical movement)
- Database: Stores user credentials and maps the Username to a specific Slot ID (A, B, C, or D) using json file.
- Hardware Communication: Upon successful login, the software sends the target slot ID to the motor control via ESP32.

**TECHNICAL SPECIFICATIONS**
- Mechanical: 4-slot Ferris wheel-style rotary structure with a central shaft and gravity-level hanging platforms.
- Actuator: DC Gear Motor equipped with a motor driver (L289N) to precisely track 90-degree steps.
- Controller: ESP32 programmed via PlatformIO (VS Code). It uses the built-in Wi-Fi to fetch JSON data from the cloud and control the motor driver (L298N).
- Frontend: HTML5, CSS3, and Vanilla JavaScript. It will use the Fetch API to send user inputs (Entry/Exit) to the backend.
- Backend: Python (Flask). This will handle the logic for user authentication, checking slot availability, and managing the JSON file.
- Data Storage: A local parking_data.json file stored on the backend server, acting as a lightweight, flat-file database.
- Hosting: Render to ensure the prototype is accessible via a public URL for free.

**HARDWARE CONNECTIONS:** 
- DC Gear Motor to OUT1 and OUT2 of the L298N motor driver
- A 12V power supply is provided to the L298N motor driver
- IN1 of the L298N motor driver to D18 of ESP32
- IN2 of the L298N motor driver to D19 of ESP32
- ENA of the L298N motor driver to D5 of ESP32
- Ground of power supply, L298N motor driver and ESP32 are connected

