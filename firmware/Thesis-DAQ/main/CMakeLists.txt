# Keep sensor register details separate from the experiment flow.
idf_component_register(SRCS "main.c" "sensors.c"
                       INCLUDE_DIRS "."
                       PRIV_REQUIRES esp_driver_i2c esp_driver_ledc esp_driver_usb_serial_jtag esp_timer)
