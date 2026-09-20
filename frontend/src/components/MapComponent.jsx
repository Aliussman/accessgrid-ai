import React, { useEffect } from 'react';
import { MapContainer, TileLayer, CircleMarker, Polyline, Popup, Tooltip, useMap, useMapEvents } from 'react-leaflet';
import { Navigation, Route, School, ShoppingBag, Hospital as HospitalIcon, X, Clock, ArrowRight, MapPin, Scissors, Link2 } from 'lucide-react';
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

// Map Click Handler for Point-to-Destination live routing or Node Closure selection
function MapClickHandler({ onMapClick }) {
  useMapEvents({
    click(e) {
      if (onMapClick) {
        onMapClick(e.latlng.lat, e.latlng.lng);
      }
    },
  });
  return null;
}

export default function MapComponent({
  centre,
  hospitals = [],
  destinations = [],
  destCategory = 'all',
  isochrones = [],
  closedGeoms = [],
  boostGeoms = [],
  riskiest = [],
  facilityCoord = null,
  alternativeRoute = null,
  originCoord = null,
  nodeClosureMode = false,
  customToolMode = 'cut',
  pointA = null,
  pointB = null,
  previewClosureGeoms = [],
  previewLinkCoords = [],
  simulatedLinkCoords = [],
  addedLinkInfo = null,
  onMapClick = null,
  onClearRoute = null,
  onClearNodeClosure = null,
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

  // Filter destinations by category
  const allDestinations = (destinations && destinations.length > 0) ? destinations : hospitals;
  const filteredDestinations = allDestinations.filter((d) => {
    if (destCategory === 'all') return true;
    return (d.category || 'hospital') === destCategory;
  });

  const getCategoryTheme = (category) => {
    switch (category) {
      case 'school':
        return { color: '#f59e0b', icon: '🏫', label: 'School / University', unit: 'students' };
      case 'market':
        return { color: '#10b981', icon: '🛒', label: 'Market / Commercial Hub', unit: 'daily footfall' };
      default:
        return { color: '#0ea5e9', icon: '🏥', label: 'Emergency Medical Center', unit: 'beds' };
    }
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
        <MapClickHandler onMapClick={onMapClick} />

        {/* High-Performance Dark Slate Base Tiles */}
        <TileLayer
          attribution='&copy; <a href="https://www.esri.com/">Esri</a> &mdash; Esri, DeLorme, NAVTEQ'
          url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
          maxZoom={16}
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

        {/* Alternative Detour Route Polyline (Emerald Green) */}
        {alternativeRoute && alternativeRoute.detour_route && alternativeRoute.detour_route.length > 0 && (
          <Polyline
            positions={alternativeRoute.detour_route}
            pathOptions={{
              color: '#10b981',
              weight: 6,
              opacity: 0.95,
              dashArray: '10, 6',
            }}
          >
            <Tooltip sticky>
              <div style={{ color: '#070a13' }}>
                <strong style={{ color: '#059669' }}>🟢 Active Alternative Detour Route</strong>
                <br />
                Detour time: {alternativeRoute.detour_time_min?.toFixed(1)} min
                {alternativeRoute.delay_min > 0 && (
                  <span style={{ color: '#dc2626' }}> (+{alternativeRoute.delay_min?.toFixed(1)}m delay)</span>
                )}
              </div>
            </Tooltip>
          </Polyline>
        )}

        {/* Baseline Original Path Polyline (Red Dashed) */}
        {alternativeRoute && alternativeRoute.is_diverted && alternativeRoute.baseline_route && alternativeRoute.baseline_route.length > 0 && (
          <Polyline
            positions={alternativeRoute.baseline_route}
            pathOptions={{
              color: '#f43f5e',
              weight: 3,
              opacity: 0.65,
              dashArray: '4, 4',
            }}
          >
            <Tooltip sticky>
              <span style={{ color: '#f43f5e' }}>🔴 Original Direct Path (Blocked/Delayed)</span>
            </Tooltip>
          </Polyline>
        )}

        {/* Interactive Click Origin Marker */}
        {originCoord && (
          <CircleMarker
            center={[originCoord.lat, originCoord.lng]}
            radius={8}
            pathOptions={{
              fillColor: '#f59e0b',
              color: '#ffffff',
              weight: 3,
              fillOpacity: 1.0,
            }}
          >
            <Tooltip permanent direction="top" offset={[0, -8]}>
              <span style={{ fontWeight: 'bold' }}>📍 Trip Origin</span>
            </Tooltip>
          </CircleMarker>
        )}

        {/* Proposed Emergency Facility */}
        {facilityCoord && (
          <CircleMarker
            center={[facilityCoord.lat, facilityCoord.lng]}
            radius={9}
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

        {/* Point-to-Point Two-Node Closure Preview Corridor */}
        {previewClosureGeoms && previewClosureGeoms.length > 0 &&
          previewClosureGeoms.map((coords, idx) => (
            <Polyline
              key={`preview-cut-${idx}`}
              positions={coords}
              pathOptions={{
                color: '#f43f5e',
                weight: 7,
                opacity: 0.9,
                dashArray: '8, 6',
              }}
            >
              <Tooltip sticky>
                <span style={{ color: '#f43f5e', fontWeight: 'bold' }}>✂️ Proposed Road Closure Corridor</span>
              </Tooltip>
            </Polyline>
          ))}

        {/* Normal Detour Route for Link Comparison (Amber Dashed) */}
        {addedLinkInfo?.route_comparison?.normal_route_coords && addedLinkInfo.route_comparison.normal_route_coords.length > 0 && (
          <Polyline
            positions={addedLinkInfo.route_comparison.normal_route_coords}
            pathOptions={{
              color: '#f59e0b',
              weight: 4,
              opacity: 0.8,
              dashArray: '6, 6',
            }}
          >
            <Tooltip sticky>
              <div style={{ color: '#070a13' }}>
                <strong style={{ color: '#d97706' }}>🚗 Normal Route Detour</strong>
                <br />
                Travel Time: {addedLinkInfo.route_comparison.normal_travel_time_min?.toFixed(1)} min
                <br />
                Distance: {addedLinkInfo.route_comparison.normal_distance_km?.toFixed(2)} km
              </div>
            </Tooltip>
          </Polyline>
        )}

        {/* Point-to-Point Temporary Link Connector Preview (Dashed Glowing Violet) */}
        {previewLinkCoords && previewLinkCoords.length > 0 && (
          <Polyline
            positions={previewLinkCoords}
            pathOptions={{
              color: '#a855f7',
              weight: 6,
              opacity: 0.95,
              dashArray: '10, 6',
            }}
          >
            <Tooltip sticky>
              <div style={{ color: '#070a13' }}>
                <strong style={{ color: '#7c3aed' }}>🔗 Proposed Temporary Link Connector</strong>
                <br />
                Connector: {addedLinkInfo?.travel_time_min?.toFixed(1)} min ({addedLinkInfo?.distance_m < 1000 ? `${addedLinkInfo?.distance_m?.toFixed(0)} m` : `${addedLinkInfo?.distance_km?.toFixed(2)} km`} @ {addedLinkInfo?.speed_kmh} km/h)
                {addedLinkInfo?.route_comparison?.has_normal_route && (
                  <>
                    <br />
                    <span style={{ color: '#059669', fontWeight: 'bold' }}>
                      ⚡ Saves {addedLinkInfo.route_comparison.time_saved_min?.toFixed(1)} min vs {addedLinkInfo.route_comparison.normal_travel_time_min?.toFixed(1)} min normal route ({addedLinkInfo.route_comparison.pct_faster?.toFixed(0)}% faster)
                    </span>
                  </>
                )}
              </div>
            </Tooltip>
          </Polyline>
        )}

        {/* Active Simulated Temporary Link (Solid Glowing Violet) */}
        {simulatedLinkCoords && simulatedLinkCoords.length > 0 && (
          <Polyline
            positions={simulatedLinkCoords}
            pathOptions={{
              color: '#c084fc',
              weight: 7,
              opacity: 0.95,
            }}
          >
            <Tooltip sticky>
              <div style={{ color: '#070a13' }}>
                <strong style={{ color: '#7c3aed' }}>🔗 Active Temporary Connector Link</strong>
                <br />
                Connector: {addedLinkInfo?.travel_time_min?.toFixed(1)} min ({addedLinkInfo?.length_km ? `${addedLinkInfo.length_km.toFixed(2)} km` : `${addedLinkInfo?.distance_km?.toFixed(2)} km`} @ {addedLinkInfo?.speed_kmh || 30} km/h)
                {addedLinkInfo?.route_comparison?.has_normal_route && (
                  <>
                    <br />
                    <span style={{ color: '#059669', fontWeight: 'bold' }}>
                      ⚡ Direct Route: -{addedLinkInfo.route_comparison.time_saved_min?.toFixed(1)} min saved ({addedLinkInfo.route_comparison.pct_faster?.toFixed(0)}% faster)
                    </span>
                  </>
                )}
                {addedLinkInfo?.destination_impact?.avg_dest_time_saved_min > 0 && (
                  <>
                    <br />
                    <span style={{ color: '#2563eb', fontWeight: 'bold' }}>
                      🏥 Hospital Access: -{addedLinkInfo.destination_impact.avg_dest_time_saved_min.toFixed(1)} min avg improvement ({addedLinkInfo.destination_impact.pop_improved_time?.toLocaleString()} residents)
                    </span>
                  </>
                )}
                {addedLinkInfo?.debt_reduced_pop_min > 0 && (
                  <>
                    <br />
                    <span style={{ color: '#059669', fontWeight: 'bold' }}>
                      📉 Debt Reduced: -{Math.round(addedLinkInfo.debt_reduced_pop_min).toLocaleString()} pop-min
                    </span>
                  </>
                )}
              </div>
            </Tooltip>
          </Polyline>
        )}

        {/* Node Selection Point A (Start) */}
        {pointA && (
          <CircleMarker
            center={[pointA.lat, pointA.lng]}
            radius={9}
            pathOptions={{
              fillColor: customToolMode === 'link' ? '#a855f7' : '#f59e0b',
              color: '#ffffff',
              weight: 3,
              fillOpacity: 1.0,
            }}
          >
            <Tooltip permanent direction="top" offset={[0, -10]}>
              <span style={{ fontWeight: 'bold', color: customToolMode === 'link' ? '#7c3aed' : '#b45309' }}>
                🅰️ Point A {pointA.node_id ? `(#${pointA.node_id})` : ''}
              </span>
            </Tooltip>
          </CircleMarker>
        )}

        {/* Node Selection Point B (End) */}
        {pointB && (
          <CircleMarker
            center={[pointB.lat, pointB.lng]}
            radius={9}
            pathOptions={{
              fillColor: customToolMode === 'link' ? '#c084fc' : '#ef4444',
              color: '#ffffff',
              weight: 3,
              fillOpacity: 1.0,
            }}
          >
            <Tooltip permanent direction="top" offset={[0, -10]}>
              <span style={{ fontWeight: 'bold', color: customToolMode === 'link' ? '#9333ea' : '#b91c1c' }}>
                🅱️ Point B {pointB.node_id ? `(#${pointB.node_id})` : ''}
              </span>
            </Tooltip>
          </CircleMarker>
        )}

        {/* Multi-Category Destinations (Hospitals, Schools, Markets) */}
        {filteredDestinations.map((d, idx) => {
          const theme = getCategoryTheme(d.category);
          return (
            <CircleMarker
              key={`dest-${d.osm_id || idx}`}
              center={[d.lat, d.lng]}
              radius={d.category === 'hospital' ? 7 : 6}
              pathOptions={{
                fillColor: theme.color,
                color: '#ffffff',
                weight: 2,
                fillOpacity: 0.92,
              }}
            >
              <Popup>
                <div style={{ color: '#070a13', minWidth: '160px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                    <span style={{ fontSize: '1.1rem' }}>{theme.icon}</span>
                    <h4 style={{ margin: '0', fontSize: '13px', fontWeight: '700' }}>{d.name}</h4>
                  </div>
                  <p style={{ margin: '0', fontSize: '11px', lineHeight: '1.4', color: '#334155' }}>
                    <strong>Category:</strong> {theme.label}
                    <br />
                    <strong>Type:</strong> {d.type}
                    <br />
                    <strong>Capacity / Scale:</strong> {d.capacity?.toLocaleString()} {theme.unit}
                    {d.service_pop !== undefined && (
                      <>
                        <br />
                        <strong>Served Catchment:</strong> {d.service_pop?.toLocaleString()}
                      </>
                    )}
                  </p>
                </div>
              </Popup>
              <Tooltip direction="top" offset={[0, -8]}>
                <span>{theme.icon} {d.name}</span>
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>

      {/* Point-to-Point Node Selection Floating Action Pill (Bottom Center) */}
      {nodeClosureMode && (
        <div style={{
          position: 'absolute',
          bottom: '20px',
          left: '50%',
          transform: 'translateX(-50%)',
          zIndex: 1000,
          background: 'rgba(15, 23, 42, 0.96)',
          backdropFilter: 'blur(12px)',
          border: `1px solid ${customToolMode === 'link' ? 'rgba(168, 85, 247, 0.7)' : 'rgba(244, 63, 94, 0.6)'}`,
          borderRadius: '24px',
          padding: '8px 18px',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.7)',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          color: '#ffffff',
          pointerEvents: 'auto',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {customToolMode === 'link' ? (
              <Link2 size={16} color="#c084fc" className="animate-pulse" />
            ) : (
              <Scissors size={16} color="var(--accent-rose)" className="animate-pulse" />
            )}
            <span style={{ fontSize: '0.78rem', fontWeight: '700' }}>
              {!pointA
                ? `Click map for ${customToolMode === 'link' ? 'Link Point' : 'Point'} 🅰️`
                : (!pointB
                ? `Click map for ${customToolMode === 'link' ? 'Link Point' : 'Point'} 🅱️`
                : (customToolMode === 'link' ? 'Temporary Link Ready' : 'Corridor Ready to Block'))}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            {pointA && (
              <span className={`badge ${customToolMode === 'link' ? 'badge-cyan' : 'badge-amber'}`} style={{ fontSize: '0.65rem' }}>
                🅰️ Set
              </span>
            )}
            {pointB && (
              <span className={`badge ${customToolMode === 'link' ? 'badge-emerald' : 'badge-rose'}`} style={{ fontSize: '0.65rem' }}>
                🅱️ Set
              </span>
            )}
            {onClearNodeClosure && (pointA || pointB) && (
              <button
                onClick={onClearNodeClosure}
                style={{
                  background: 'rgba(255, 255, 255, 0.1)',
                  border: '1px solid rgba(255, 255, 255, 0.2)',
                  color: '#ffffff',
                  borderRadius: '12px',
                  padding: '2px 8px',
                  fontSize: '0.65rem',
                  cursor: 'pointer',
                }}
              >
                Reset
              </button>
            )}
          </div>
        </div>
      )}

      {/* Interactive Alternative Route Card Overlay (Bottom Right) */}
      {alternativeRoute && alternativeRoute.success && (
        <div style={{
          position: 'absolute',
          bottom: '20px',
          right: '16px',
          zIndex: 1000,
          background: 'rgba(15, 23, 42, 0.94)',
          backdropFilter: 'blur(12px)',
          border: '1px solid rgba(16, 185, 129, 0.4)',
          borderRadius: '10px',
          padding: '10px 14px',
          maxWidth: '300px',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.6)',
          color: '#f8fafc',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Route size={15} color="var(--accent-emerald)" />
              <span style={{ fontSize: '0.78rem', fontWeight: '700', color: 'var(--accent-emerald)' }}>
                {alternativeRoute.is_diverted ? 'Alternative Detour Route' : 'Direct Route'}
              </span>
            </div>
            {onClearRoute && (
              <button
                onClick={onClearRoute}
                style={{ background: 'transparent', border: 'none', color: '#94a3b8', cursor: 'pointer', padding: '2px' }}
                title="Clear route"
              >
                <X size={14} />
              </button>
            )}
          </div>

          <div style={{ fontSize: '0.72rem', color: '#cbd5e1', marginBottom: '6px' }}>
            To: <strong>{alternativeRoute.destination?.name || 'Nearest Facility'}</strong>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px', background: 'rgba(0, 0, 0, 0.3)', padding: '5px 8px', borderRadius: '6px' }}>
            <div>
              <div style={{ fontSize: '0.62rem', color: '#94a3b8' }}>Normal</div>
              <div style={{ fontSize: '0.8rem', fontWeight: '700', color: '#94a3b8' }}>
                {alternativeRoute.baseline_time_min ? `${alternativeRoute.baseline_time_min.toFixed(1)}m` : 'N/A'}
              </div>
            </div>

            <ArrowRight size={12} color="#64748b" />

            <div>
              <div style={{ fontSize: '0.62rem', color: 'var(--accent-emerald)' }}>Detour</div>
              <div style={{ fontSize: '0.8rem', fontWeight: '700', color: 'var(--accent-emerald)' }}>
                {alternativeRoute.detour_time_min ? `${alternativeRoute.detour_time_min.toFixed(1)}m` : 'N/A'}
              </div>
            </div>

            <div>
              <div style={{ fontSize: '0.62rem', color: alternativeRoute.delay_min > 0 ? 'var(--accent-rose)' : 'var(--accent-emerald)' }}>
                Delay
              </div>
              <div style={{ fontSize: '0.8rem', fontWeight: '700', color: alternativeRoute.delay_min > 0 ? 'var(--accent-rose)' : 'var(--accent-emerald)' }}>
                {alternativeRoute.delay_min > 0 ? `+${alternativeRoute.delay_min.toFixed(1)}m` : '0m'}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

