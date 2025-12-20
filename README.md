# dabidotcom
Dabis Own Website

Gives Dabi (or anyone) the ability to dynamically create their own pages!

## Getting Started
After cloning the repo, run `docker dompose up -d --build` to build and run the container.

## Test / Sample pages

### Hello World
```
curl -X POST http://localhost:8000/api/pages \
  -H "X-API-Key: abc123" \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "first-page",
    "title": "First Page",
    "markdown": "# Hello World\n\nThis is the first test page created manually."
  }'
```

### Goodbye World
```
curl -X POST http://localhost:8000/api/pages \
  -H "X-API-Key: abc123" \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "second-page",
    "title": "Goodbye Page",
    "markdown": "<div style=\"background-color: #90EE90; padding: 2em;\">\n<h1>Goodbye World</h1>\n<p>This page has a green background.</p>\n</div>"
  }'
```

## Deleting pages
```
curl -X DELETE http://localhost:8000/api/pages/first-page \
  -H "X-API-Key: abc123"
```
