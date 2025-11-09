<-------------------- | ------------ | markdownlint-disable MD022 MD013 -->
# Somfy API Endpoints

This document lists the API endpoints for the Somfy-based Phantom Blinds system.

## Base URL Pattern

```
http://{gateway_ip}/
```

## Gateway Endpoints

### Get Gateway Information
```
GET /gateway
```
Returns basic gateway information and capabilities.

### Get Home Configuration
```
GET /home
```
Returns complete home configuration including rooms, shades, and scenes.

## Room Endpoints

### List All Rooms
```
GET /home/rooms
```

### Get Room Details
```
GET /home/rooms/{room_id}
```

## Shade Endpoints

### Get Shade Details
```
GET /home/shades/{shade_id}
```

### Move Shade
```
PUT /home/shades/{shade_id}/motion
```
**Request Body:**
```json
{
  "positions": {
    "primary": 0-100,
    "secondary": 0-100,
    "tilt": 0-100,
    "velocity": 0-100
  }
}
```

### Get Shade Positions
```
GET /home/shades/positions?ids={shade_id}
```

### Stop Shade
```
PUT /home/shades/stop?ids={shade_id}
```

## Scene Endpoints

### Get Scene Details
```
GET /home/scenes/{scene_id}
```

### Activate Scene
```
PUT /home/scenes/{scene_id}/activate
```

### Get Active Scenes
```
GET /home/scenes/active
```

### Scene Events (SSE)
```
GET /home/scenes/events
```
Server-Sent Events endpoint for scene updates.

## Event Endpoints

### Home Events (SSE)
```
GET /home/events?sse=false&raw=true
```
Main event stream for all home updates.

### Shade Events (SSE)
```
GET /home/shades/events
```
Server-Sent Events endpoint for shade status updates.

## Response Codes

- `200 OK` - Request successful
- `400 Bad Request` - Invalid request or not primary gateway
- `404 Not Found` - Resource not found
- `503 Service Unavailable` - PowerView setup not complete

## Authentication

**TODO**: Document authentication requirements for Somfy API
- API keys (if required)
- OAuth (if used)
- Basic auth (if used)

## Rate Limiting

**TODO**: Document any rate limiting policies

## Notes

- Most endpoints accept and return `application/json`
- SSE endpoints stream text/event-stream
- Position values are typically 0-100 (percentage)
- The gateway parameter can be an IP address or hostname (e.g., "powerview-g3.local")
