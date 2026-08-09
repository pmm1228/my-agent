from app.tools.weather.current import get_weather
from app.tools.weather.typhoon import get_typhoon


weather_tools = [get_weather, get_typhoon]


__all__ = ["weather_tools", "get_weather", "get_typhoon"]
