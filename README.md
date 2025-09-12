# Ampio Custom Component for Home Assistant

Ampio is a custom integration for Home Assistant that enables seamless communication with Ampio smart home devices. This integration allows you to monitor and control your Ampio system directly from Home Assistant, providing enhanced automation and convenience.

## Features

- Discover and control Ampio devices
- Monitor device states and sensor data
- Integrate Ampio devices into Home Assistant automations and dashboards

## Installation

### HACS (Recommended)

1. Go to **HACS > Integrations** in your Home Assistant UI.
2. Click the three dots in the top right and select **Custom repositories**.
3. Add this repository URL:  
    `https://github.com/kstaniek/hacs-ampio`
4. Select **Integration** as the category.
5. Search for "Ampio" in HACS and install the integration.
6. Restart Home Assistant.

### Manual

1. Download the `custom_components/ampio` directory from this repository.
2. Copy it into your Home Assistant `custom_components` directory.
3. Restart Home Assistant.

## Configuration

After installation, configure the integration via the Home Assistant UI:

1. Go to **Settings > Devices & Services**.
2. Click **Add Integration** and search for "Ampio".
3. Follow the setup instructions.

## Support

For issues or feature requests, please open an issue on the [GitHub repository](https://github.com/kstaniek/hacs-ampio/issues).

## License

By providing a contribution, you agree the contribution is licensed under Apache-2.0. This is required for Home Assistant contributions.


## Requirements

- **Ampio configuration must be provided via an external URL.**  
    Example configuration files are available at [kstaniek/ampio-config](https://github.com/kstaniek/ampio-config).

- **Waveshare 2-CH-CAN-TO-ETH gateway is required** for communication between Home Assistant and Ampio devices.