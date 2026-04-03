import usb_cdc
import usb_hid
import storage
import supervisor

# disable_usb_drive() ya da acceso de escritura completo a CircuitPython
# (remount no es necesario y puede provocar que la unidad siga apareciendo)
storage.disable_usb_drive()

# Habilitar solo consola serial (CDC) y mouse HID
usb_cdc.enable(console=True, data=False)
usb_hid.enable((usb_hid.Device.MOUSE,))

# Identificación USB personalizada
supervisor.set_usb_identification(
    manufacturer="Logitech",
    product="USB Optical Mouse",
    serial_number="LGTCH-M248"
)
