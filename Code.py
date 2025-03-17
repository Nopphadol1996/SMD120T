import urequests 
import time
from machine import UART, Pin
import struct
import network

# ตั้งค่า InfluxDB
INFLUX_HOST = "http://172.20.10.4" # เปลี่ยน
INFLUX_PORT = 8086
INFLUX_DB = "PROJECT"

# กำหนดชื่อ Wi-Fi และรหัสผ่าน
SSID = "iPhone"
PASSWORD = "11501150"

# สร้างอ็อบเจ็กต์ Wi-Fi
wlan = network.WLAN(network.STA_IF)
wlan.active(True)

# เชื่อมต่อ Wi-Fi
print("Connecting to Wi-Fi...")
wlan.connect(SSID, PASSWORD)

while not wlan.isconnected():
    print(".", end="")
    time.sleep(1)

print("\nConnected!")
print("IP Address:", wlan.ifconfig()[0])

# ตั้งค่า UART สำหรับ RS-485
uart = UART(1, baudrate=9600, tx=Pin(4), rx=Pin(5), parity=None, stop=1)

# ฟังก์ชัน CRC-16 (Modbus CRC)
def calculate_crc(data):
    crc = 0xFFFF
    for pos in data:
        crc ^= pos
        for _ in range(8):
            if (crc & 0x0001) != 0:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc & 0xFF, (crc >> 8) & 0xFF

# ฟังก์ชันสร้างคำขอ Modbus RTU
def create_modbus_request(device_id, function_code, start_address, quantity):
    request = bytearray()
    request.append(device_id)
    request.append(function_code)
    request.append((start_address >> 8) & 0xFF)
    request.append(start_address & 0xFF)
    request.append((quantity >> 8) & 0xFF)
    request.append(quantity & 0xFF)
    crc_low, crc_high = calculate_crc(request)
    request.append(crc_low)
    request.append(crc_high)
    return request

# ฟังก์ชันแปลงข้อมูล Modbus เป็น IEEE 754 Floating Point
def parse_ieee754_float(data):
    if len(data) == 4:
        raw_bytes = bytes(data)
        value = struct.unpack('>f', raw_bytes)[0]
        return value
    else:
        print("ข้อมูลไม่สมบูรณ์")
        return None

# ฟังก์ชันอ่านข้อมูล Modbus RTU
def read_modbus(device_id, start_address, quantity):
    request = create_modbus_request(device_id, 0x04, start_address, quantity)
    uart.write(request)
    time.sleep(0.2)
    response = uart.read(9)
    if response:
        received_crc = (response[-2], response[-1])
        calculated_crc = calculate_crc(response[:-2])
        if received_crc != calculated_crc:
            print("CRC ไม่ถูกต้อง")
            return None
        data = response[3:7]
        return parse_ieee754_float(data)
    else:
        print("ไม่มีการตอบกลับ")
        return None

# ฟังก์ชันอ่านพารามิเตอร์ทั้งหมด
def read_all_parameters(device_id):
    parameters = {
        "Voltage": 0x0000,
        "Current": 0x0006,
        "ActivePower": 0x000C,
        "ApparentPower": 0x0012,
        "ReactivePower": 0x0018,
        "PowerFactor": 0x001E,
        "Frequency": 0x0046,
        "TotalActiveEnergy": 0x0156
    }
    results = {}
    for name, address in parameters.items():
        value = read_modbus(device_id, address, 2)
        results[name] = value if value is not None else "Error"
    return results

# อัตราค่าไฟฟ้า (บาทต่อ kWh)
RATE = 4.15  # เปลี่ยนตามอัตราค่าไฟของคุณ

# ฟังก์ชันคำนวณค่าไฟฟ้า
def calculate_electricity_cost(total_active_energy_kWh):
    if total_active_energy_kWh is not None:
        return total_active_energy_kWh * RATE
    return 0

# ฟังก์ชันส่งข้อมูลไปยัง InfluxDB 1.8.10 (ใช้ Line Protocol)
def send_to_influx(data):
    url = f"{INFLUX_HOST}:{INFLUX_PORT}/write?db={INFLUX_DB}"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    try:
        response = urequests.post(url, data=data, headers=headers)
        print("InfluxDB Response:", response.status_code, response.text)
        response.close()
    except Exception as e:
        print("Failed to send data to InfluxDB:", e)

# วนลูปหลัก
def main():
    device_id = 1
    while True:
        results = read_all_parameters(device_id)
        line_protocol = ""

        print("\n=== ข้อมูลจาก SDM120 ===")
        for name, value in results.items():
            if value != "Error":
                print(f"{name}: {value:.2f}")

                # สร้าง Line Protocol
                line_protocol += f"power_monitor,location=main_panel {name.lower()}={value}\n"

        # ส่งข้อมูลไปยัง InfluxDB
        if line_protocol:
            send_to_influx(line_protocol)
        
        time.sleep(5)

main()
