import React, { useEffect } from 'react';
import { MapContainer, TileLayer, CircleMarker, Polyline, Marker, Popup, Tooltip, useMap } from 'react-leaflet';
import L from 'leaflet';

// Fix for default Leaflet icon assets
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

// Helper component to recenter map
function MapUpdater({ centre }) {
  const map = useMap();
  useEffect(() => {
    if (centre && centre.lat && centre.lng) {
      map.setView([centre.lat, centre.lng], 12);
    }
  }, [centre, map]);
  return null;
}

export default function MapComponent({
  centre,
  hospitals = [],
  isochrones = [],
  closedGeoms = [],
  boostGeoms = [],
  riskiest = [],
  facilityCoord = null,
  showIsochrones = true,
  showRiskiest = true,
}) {
  const defaultPos = [centre?.lat || 30.71, centre?.lng || 76.75];

  const getIsoColor = (time) => {
    if (time < 5.0) return '#10b981'; // Rapid (<5m)
    if (time < 10.0) return '#3b82f6'; // Standard (5-10m)
    if (time < 15.0) return '#f59e0b'; // Threshold Buffer (10-15m)
    if (time < 20.0) return '#f97316'; // Delayed (15-20m)
    return '#ef4444'; // Isolated / Severe delay (>20m)
  };

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <MapContainer
        center={defaultPos}
        zoom={12}
        style={{ width: '100%', height: '100%', background: '#070a13' }}
        zoomControl={false}
      >
        <MapUpdater centre={centre} />

        {/* Dark Matter Base Tiles */}
        <TileLayer
          attribution='&copy; <a href="https://carto.com/">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        />

        {/* Riskiest Corridors */}
        {showRiskiest &&
          riskiest.map((r, idx) => (
            <Polyline
              key={`risk-${idx}`}
              positions={r.coords}
              pathOptions={{
                color: r.score >= 85 ? '#ef4444' : '#f59e0b',
                weight: 3,
                opacity: 0.6,
                dashArray: '4, 6',
              }}
            >
              <Tooltip sticky>
                <div>
                  <strong>Corridor Risk: {r.score.toFixed(0)}/100</strong>
                  <br />
                  Affected pop if cut: {r.affected?.toLocaleString()}
                </div>
              </Tooltip>
            </Polyline>
          ))}

        {/* Isochrone Catchment Points */}
        {showIsochrones &&
          isochrones.map((pt, idx) => (
            <CircleMarker
              key={`iso-${pt.id || idx}`}
              center={[pt.lat, pt.lng]}
              radius={3}
              pathOptions={{
                fillColor: getIsoColor(pt.time),
                fillOpacity: 0.55,
                stroke: false,
              }}
            >
              <Tooltip sticky>
                <div>
                  <strong>Travel time: {pt.time >= 999 ? 'Isolated (>20m)' : `${pt.time.toFixed(1)} min`}</strong>
                  <br />
                  Local population: {pt.pop?.toLocaleString()}
                </div>
              </Tooltip>
            </CircleMarker>
          ))}

        {/* Closed Segments (Bold Red) */}
        {closedGeoms.map((coords, idx) => (
          <Polyline
            key={`closed-${idx}`}
            positions={coords}
            pathOptions={{
              color: '#ef4444',
              weight: 6,
              opacity: 0.95,
            }}
          >
            <Tooltip sticky>
              <span style={{ color: '#ef4444', fontWeight: 'bold' }}>⛔ Road Segment Closed</span>
            </Tooltip>
          </Polyline>
        ))}

        {/* Emergency Priority Corridors (Green) */}
        {boostGeoms.map((coords, idx) => (
          <Polyline
            key={`boost-${idx}`}
            positions={coords}
            pathOptions={{
              color: '#10b981',
              weight: 5,
              opacity: 0.9,
              dashArray: '8, 4',
            }}
          >
            <Tooltip sticky>
              <span style={{ color: '#10b981', fontWeight: 'bold' }}>⚡ Emergency Priority Corridor (0.7x Speed)</span>
            </Tooltip>
          </Polyline>
        ))}

        {/* Proposed Emergency Facility */}
        {facilityCoord && (
          <CircleMarker
            center={[facilityCoord.lat, facilityCoord.lng]}
            radius={8}
            pathOptions={{
              fillColor: '#a855f7',
              color: '#ffffff',
              weight: 2,
              fillOpacity: 0.95,
            }}
          >
            <Popup>
              <div style={{ color: '#070a13' }}>
                <strong>🏥 Proposed Emergency Facility</strong>
                <br />
                Node ID: {facilityCoord.node_id}
              </div>
            </Popup>
          </CircleMarker>
        )}

        {/* Hospitals */}
        {hospitals.map((h, idx) => (
          <CircleMarker
            key={`hosp-${h.osm_id || idx}`}
            center={[h.lat, h.lng]}
            radius={7}
            pathOptions={{
              fillColor: '#0ea5e9',
              color: '#ffffff',
              weight: 2,
              fillOpacity: 0.9,
            }}
          >
            <Popup>
              <div style={{ color: '#070a13' }}>
                <h4 style={{ margin: '0 0 4px 0', fontSize: '14px', fontWeight: '700' }}>{h.name}</h4>
                <p style={{ margin: '0', fontSize: '12px' }}>
                  <strong>Type:</strong> {h.type}
                  <br />
                  <strong>Capacity:</strong> {h.capacity} beds
                  <br />
                  <strong>Served Pop:</strong> {h.service_pop?.toLocaleString()}
                </p>
              </div>
            </Popup>
            <Tooltip direction="top" offset={[0, -8]}>
              <span>{h.name}</span>
            </Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  );
}
