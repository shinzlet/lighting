from .lighting import get_hub, get_device_set_by_name

def main():
    hub = get_hub()
    lights = hub.get_lights()

    [b1, b2] = get_device_set_by_name(lights, "Ceiling Lamp")

    ll = 70
    b1.set_light_level(ll)
    b2.set_light_level(ll)
    b1.set_color_temperature(4000)

    hue = 0.0
    saturation = 0.0

    while True:
        command = input("Enter command (h FLOAT or s FLOAT), or 'q' to quit: ").strip()
        
        if command.lower() == 'q':
            break
        
        parts = command.split()
        
        if len(parts) == 2:
            try:
                variable = parts[0].lower()
                value = float(parts[1])
                
                if variable == 'h':
                    hue = value
                elif variable == 's':
                    saturation = value
                elif variable == 't':
                    b1.set_color_temperature(int(value))
                    print(f"Set bulb 1 color temperature to {int(value)}")
                else:
                    print("Invalid command. Use 'h' for hue or 's' for saturation.")
            except ValueError:
                print("Invalid number format.")
        else:
            print("Invalid command format. Use 'h FLOAT' or 's FLOAT'.")
        
        print(f"Hue: {hue}, Saturation: {saturation}")
        b2.set_light_color(hue, saturation)


if __name__ == "__main__":
    main()