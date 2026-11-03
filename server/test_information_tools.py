import datetime as dt
import json
import socket
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch
import information_tools as t
import provider


def address(ip):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443))]


class ToolTests(unittest.TestCase):
    def test_percent_and_decimal(self):
        self.assertEqual(t.calculate('2400*15/100')['result'], '360')
        self.assertEqual(t.calculate('0.1+0.2')['result'], '0.3')
        self.assertEqual(t.calculate('(10-2)**2/4')['result'], '16')

    def test_reject_code_and_resource_exhaustion(self):
        for expression in ("__import__('os').system('whoami')", '2**999999', '(1).__class__', '[1]*9', '1/0', '1e999999'):
            with self.subTest(expression=expression):
                self.assertEqual(t.execute('calculate', {'expression': expression})['status'], 'error')

    def test_units(self):
        self.assertEqual(t.convert_units('5', 'mile', 'km')['result'], '8.04672')
        self.assertEqual(t.convert_units('32', 'f', 'c')['result'], '0')
        self.assertEqual(t.convert_units('1', 'm/s', 'km/h')['result'], '3.6')
        self.assertEqual(t.convert_units('36', 'km/h', 'm/s')['result'], '10')
        self.assertEqual(t.execute('convert_units', {'value': '1', 'from_unit': 'kg', 'to_unit': 'km'})['status'], 'error')
        self.assertEqual(t.execute('convert_units', {'value': '-1', 'from_unit': 'k', 'to_unit': 'c'})['status'], 'error')

    def test_missing_city_never_uses_network(self):
        with patch.object(t, 'get_json', side_effect=AssertionError('No network')):
            self.assertEqual(t.get_weather()['status'], 'needs_city')

    def test_city_not_found_and_ambiguous(self):
        with patch.object(t, 'get_json', return_value={}):
            self.assertEqual(t.get_weather('unknown')['status'], 'city_not_found')
        with patch.object(t, 'get_json', return_value={'results': [{'name': 'A', 'population': 100000}, {'name': 'B', 'population': 90000}]}):
            self.assertEqual(t.get_weather('ambiguous')['status'], 'ambiguous_city')

    def test_weather_units_local_dates_and_source(self):
        places = {'results': [{'name': 'Москва', 'latitude': 55.7, 'longitude': 37.6, 'country': 'Россия'}]}
        forecast = {'timezone': 'Europe/Moscow', 'current': {'temperature_2m': 3}, 'daily': {'time': ['2026-11-02']}, 'current_units': {'wind_speed_10m': 'm/s'}}
        with patch.object(t, 'get_json', side_effect=[places, forecast]) as fetch:
            result = t.get_weather('Москва')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['timezone'], 'Europe/Moscow')
        self.assertEqual(dt.date.fromisoformat(result['tomorrow']) - dt.date.fromisoformat(result['today']), dt.timedelta(days=1))
        self.assertIn('wind_speed_unit=ms', fetch.call_args.args[0])
        self.assertEqual(result['source'], 'Open-Meteo')

    def test_public_url_blocks_private_mixed_dns_and_ports(self):
        for url in ('file:///etc/passwd', 'http://localhost/', 'http://127.0.0.1/', 'https://example.org:8765/', 'https://user:pass@example.org/', 'http://169.254.169.254/', 'http://[::1]/'):
            with self.subTest(url=url), patch.object(t.socket, 'getaddrinfo', return_value=address('127.0.0.1')):
                with self.assertRaises(ValueError): t.public_target(url)
        with patch.object(t.socket, 'getaddrinfo', return_value=address('93.184.216.34')+address('10.0.0.1')):
            with self.assertRaises(ValueError): t.public_target('https://example.org')

    def test_redirect_revalidates_private_target(self):
        response = S(status=302, getheader=lambda name: 'http://127.0.0.1/private')
        connection = S(request=lambda *a, **k: None, getresponse=lambda: response, close=lambda: None)
        with patch.object(t.socket, 'getaddrinfo', side_effect=[address('93.184.216.34'), address('127.0.0.1')]), patch.object(t.http.client, 'HTTPConnection', return_value=connection):
            with self.assertRaises(ValueError): t.public_get('http://example.org')

    def test_page_removes_scripts_and_bounds_text(self):
        with patch.object(t, 'public_get', return_value=('<title>Title</title><script>secret()</script><p>Useful text</p>', 'https://example.org', 'text/html')):
            result = t.fetch_page('https://example.org')
        self.assertEqual(result['title'], 'Title')
        self.assertNotIn('secret', result['text'])
        self.assertIn('Useful text', result['text'])


class Message:
    def __init__(self, content=None, calls=None):
        self.content, self.tool_calls = content, calls

    def model_dump(self, **kwargs):
        return {'role': 'assistant', 'tool_calls': [{'id': c.id, 'type': 'function', 'function': {'name': c.function.name, 'arguments': c.function.arguments}} for c in self.tool_calls]}


def call(name, arguments, ident='test'):
    return S(id=ident, function=S(name=name, arguments=json.dumps(arguments)))


class RoutingTests(unittest.TestCase):
    def run_responses(self, text, responses, history=None):
        captured = []
        replies = iter(responses)
        def create(**kwargs):
            captured.append(kwargs)
            return S(choices=[S(message=next(replies))])
        api = S(chat=S(completions=S(create=create)))
        with patch.object(provider, 'client', return_value=api), patch.object(provider, 'resolve', return_value='gpt-6-luna'):
            result = provider.generate(history or [], text, 'ru')
        return result, captured

    def test_weather_forces_tool_and_city_clarification(self):
        with patch.dict(t.HANDLERS), patch.dict(t.HANDLERS, {'get_weather': unittest.mock.Mock(return_value={'status': 'needs_city'})}):
            weather = t.HANDLERS['get_weather']
            result, captured = self.run_responses('Какая погода завтра?', [Message(calls=[call('get_weather', {'city': ''})]), Message('В каком городе?')], [{'role': 'user', 'content': 'Я в Москве'}])
        self.assertEqual(captured[0]['tool_choice']['function']['name'], 'get_weather')
        weather.assert_called_once_with(city='')
        self.assertEqual(result[0], 'В каком городе?')

    def test_multiple_rounds_search_then_page(self):
        with patch.object(provider, 'search', return_value={'results': [{'title': 'source', 'url': 'https://example.org'}]}), patch.dict(t.HANDLERS, {'fetch_page': lambda **kwargs: {'url': 'https://example.org', 'text': 'source contents'}}):
            result, captured = self.run_responses('Найди информацию', [Message(calls=[call('search_web', {'query': 'test'})]), Message(calls=[call('fetch_page', {'url': 'https://example.org'}, 'page')]), Message('Проверенный ответ')])
        self.assertEqual(len(captured), 3)
        self.assertEqual(captured[1]['tool_choice'], 'auto')
        self.assertEqual(result[0], 'Проверенный ответ')

    def test_tool_failure_is_visible_to_model(self):
        with patch.object(provider, 'search', side_effect=TimeoutError):
            result, captured = self.run_responses('Найди информацию', [Message(calls=[call('search_web', {'query': 'test'})]), Message('Поиск временно недоступен')])
        tool_message = next(m for m in captured[-1]['messages'] if m['role'] == 'tool')
        self.assertEqual(json.loads(tool_message['content'])['status'], 'error')
        self.assertEqual(result[1], [])


if __name__ == '__main__':
    unittest.main()
