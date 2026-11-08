"""Sample log lines shared by the tests."""

GOOD_LINE = '2026-11-06T09:00:00Z 10.0.2.17 "GET /api/products/381 HTTP/1.1" 200 23ms'
SAMPLE_LINES = [
    GOOD_LINE,
    '2026-11-06T09:00:01Z 10.0.1.5 "POST /api/check',
    "<html>502 Bad Gateway</html>",
    '2026-11-06T09:00:02Z 10.0.3.9 "BREW /api/products HTTP/1.1" 200 41ms',
    '2026-11-06T09:00:03Z 10.0.0.4 "GET /health HTTP/1.1" 999 2ms',
    '2026-11-06T09:00:04Z 10.0.0.5 "POST /api/checkout HTTP/1.1" 503 1250ms',
]
