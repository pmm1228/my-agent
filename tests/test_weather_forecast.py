import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from app.tools.weather.forecast import get_weather_forecast


class WeatherForecastTests(unittest.TestCase):
    def test_geocoder_selects_matching_location_instead_of_first_result(self):
        today = date.today().isoformat()
        geo = MagicMock()
        geo.json.return_value = {"results": [
            {"name": "上海镇", "admin1": "其他省", "country": "中国", "latitude": 1, "longitude": 1},
            {"name": "上海市", "admin1": "上海", "country": "中国", "latitude": 31.2, "longitude": 121.5},
        ]}
        forecast = MagicMock()
        forecast.json.return_value = {"daily": {
            "time": [today],
            "weather_code": [0],
            "temperature_2m_min": [20],
            "temperature_2m_max": [28],
            "precipitation_probability_max": [10],
        }}
        client = MagicMock()
        client.get.side_effect = [geo, forecast]
        manager = MagicMock()
        manager.__enter__.return_value = client
        with patch("app.tools.weather.forecast.http_client", return_value=manager):
            result = get_weather_forecast("上海", today, today)

        self.assertEqual(result["status"], "available")
        self.assertIn("上海市", result["resolved_location"])
        forecast_params = client.get.call_args_list[1].kwargs["params"]
        self.assertEqual(forecast_params["latitude"], 31.2)

    def test_ambiguous_location_is_not_silently_accepted(self):
        geo = MagicMock()
        geo.json.return_value = {"results": [
            {"name": "完全不同", "latitude": 1, "longitude": 1},
        ]}
        client = MagicMock()
        client.get.return_value = geo
        manager = MagicMock()
        manager.__enter__.return_value = client
        with patch("app.tools.weather.forecast.http_client", return_value=manager):
            result = get_weather_forecast("上海", "2099-01-01", "2099-01-02")

        self.assertEqual(result["status"], "location_ambiguous")
        self.assertEqual(client.get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
