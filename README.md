# Weather Station Web Interface

A Flask-based web application that provides a real-time interface for weather station data with MongoDB integration and OpenWeather API comparison features.

## Features

- Real-time weather data display using WebSocket
- Historical data visualization
- Weather data comparison with OpenWeather API
- Configurable alert system for temperature and humidity thresholds
- Rainfall tracking and analysis
- Responsive web interface

## Prerequisites

- Python 3.12 or newer
- MongoDB database
- OpenWeather API key (for forecast comparison)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/BogdanVereshchak/MeteostationFlaskAPI.git
cd MeteostationFlaskAPI
```

2. Create and activate a virtual environment:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. Install the required dependencies:
```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Configuration

1. Create a `config/config_db.py` file with your MongoDB credentials and OpenWeather API settings:
```python
MONGO_URI = "your_mongodb_connection_string"
DB_NAME = "your_database_name"
COLLECTION_NAME = "weather_data"
CONFIG_NAME = "config"

# OpenWeather API configuration
OPENWEATHER_API_KEY = "your_api_key"
WEATHER_LOCATION_LAT = your_latitude
WEATHER_LOCATION_LON = your_longitude
```

## Usage

1. Start the Flask application:
```powershell
python app.py
```

2. Access the web interface at:
- Main interface: `http://localhost:3000/`
- History page: `http://localhost:3000/web/history`
- Settings page: `http://localhost:3000/web/settings`
- Comparison page: `http://localhost:3000/web/comparison`

## API Endpoints

- `/api/data` - POST: Submit weather station data, GET: Retrieve recent data
- `/api/data/all` - GET: Retrieve all historical data
- `/api/data/stats` - GET: Get statistical data with rainfall analysis
- `/api/weather/forecast` - GET: Fetch current weather from OpenWeather API
- `/api/weather/comparison` - GET: Compare station data with forecast
- `/api/config` - GET/POST: Manage alert thresholds and system configuration

## Project Structure

```
IS_project/
├── app.py                # Main Flask application
├── requirements.txt      # Python dependencies
├── .venv/               # Virtual environment (ignored in Git)
├── config/
│   └── config_db.py     # Database configuration
├── templates/           # HTML templates
├── static/             # CSS/JS files
└── README.md
```

## License

[MIT License](LICENSE)

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request