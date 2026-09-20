import React, { useState, useEffect } from 'react';
import {
  Activity,
  ShieldAlert,
  Bot,
  Zap,
  Clock,
  RotateCcw,
  Sliders,
  Layers,
  FileDown,
  Navigation,
  CheckCircle2,
  AlertTriangle,
} from 'lucide-react';

import MapComponent from './components/MapComponent';
import ScenarioStudio from './components/ScenarioStudio';
import HospitalSurgePanel from './components/HospitalSurgePanel';
import InterventionsPanel from './components/InterventionsPanel';
import CopilotPanel from './components/CopilotPanel';

export default function App() {
  const [overview, setOverview] = useState(null);
  const [presets, setPresets] = useState({});
  const [roads, setRoads] = useState([]);
  const [threshold, setThreshold] = useState(15);
  const [destCategory, setDestCategory] = useState('all');
  const [showAltRoute, setShowAltRoute] = useState(true);
  const [clickedRoute, setClickedRoute] = useState(null);
  const [originCoord, setOriginCoord] = useState(null);
  const [activeScenario, setActiveScenario] = useState(null);
  const [selectedIntervention, setSelectedIntervention] = useState(null);
  const [activeTab, setActiveTab] = useState('surge');
  const [showIsochrones, setShowIsochrones] = useState(true);
  const [showRiskiest, setShowRiskiest] = useState(true);
  const [loading, setLoading] = useState(false);

  // Point-to-Point Two-Node Closure & Link States
  const [nodeClosureMode, setNodeClosureMode] = useState(false);
  const [customToolMode, setCustomToolMode] = useState('cut'); // 'cut' | 'link'
  const [linkSpeed, setLinkSpeed] = useState(30);
  const [pointA, setPointA] = useState(null);
  const [pointB, setPointB] = useState(null);
  const [nodeClosureResolved, setNodeClosureResolved] = useState(null);
  const [isResolvingNodes, setIsResolvingNodes] = useState(false);
  const [addedLinkResolved, setAddedLinkResolved] = useState(null);
  const [isResolvingLink, setIsResolvingLink] = useState(false);

  // Initial Load
  useEffect(() => {
    fetchOverview(threshold, destCategory);
    fetch('/api/presets')
      .then((r) => r.json())
      .then((data) => setPresets(data))
      .catch((e) => console.error('Error fetching presets:', e));
    fetch('/api/roads')
      .then((r) => r.json())
      .then((data) => setRoads(data))
      .catch((e) => console.error('Error fetching roads:', e));
  }, []);

  const fetchOverview = async (thresh, cat = 'all') => {
    try {
      const res = await fetch(`/api/overview?threshold=${thresh}&category=${cat}`);
      const data = await res.json();
      setOverview(data);
    } catch (e) {
      console.error('Error fetching overview:', e);
    }
  };

  const handleThresholdChange = (val) => {
    setThreshold(val);
    fetchOverview(val, destCategory);
    if (activeScenario) {
      handleRunScenario({ ...activeScenario.params, threshold: val, category: destCategory });
    }
  };

  const handleDestCategoryChange = (cat) => {
    setDestCategory(cat);
    fetchOverview(threshold, cat);
    if (originCoord && !nodeClosureMode) {
      // Re-calculate route for new destination category
      handleMapClick(originCoord.lat, originCoord.lng, cat);
    }
  };

  const handleRunScenario = async (params) => {
    setLoading(true);
    setSelectedIntervention(null);
    setClickedRoute(null);
    setOriginCoord(null);
    try {
      const res = await fetch('/api/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...params, threshold, category: destCategory }),
      });
      const data = await res.json();
      setActiveScenario({ ...data, params });
      if (data.candidates && data.candidates.length > 0) {
        setActiveTab('surge');
      }
    } catch (err) {
      console.error('Simulation error:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleMapClick = async (lat, lng, targetCategory = destCategory) => {
    // If in Two-Node Map Selection Mode (Cut or Add Link)
    if (nodeClosureMode) {
      if (!pointA) {
        setPointA({ lat, lng });
        setPointB(null);
        setNodeClosureResolved(null);
        setAddedLinkResolved(null);
      } else if (!pointB) {
        setPointB({ lat, lng });
        if (customToolMode === 'link') {
          setIsResolvingLink(true);
          try {
            const resolvePayload = {
              lat1: pointA.lat,
              lng1: pointA.lng,
              lat2: lat,
              lng2: lng,
              speed_kmh: linkSpeed,
            };
            if (activeScenario?.params?.preset_id) {
              resolvePayload.preset_id = activeScenario.params.preset_id;
            } else if (activeScenario?.params?.road) {
              resolvePayload.road = activeScenario.params.road;
            } else if (activeScenario?.closed_edges) {
              resolvePayload.closed_edges = activeScenario.closed_edges;
            }

            const res = await fetch('/api/resolve-link', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(resolvePayload),
            });
            if (res.ok) {
              const data = await res.json();
              setAddedLinkResolved(data);
              setPointA((prev) => ({ ...prev, node_id: data.node_a }));
              setPointB({ lat, lng, node_id: data.node_b });
            } else {
              const errData = await res.json().catch(() => ({}));
              alert(errData.detail || 'Could not resolve temporary connector between selected points.');
              setPointB(null);
            }
          } catch (err) {
            console.error('Error resolving link:', err);
          } finally {
            setIsResolvingLink(false);
          }
        } else {
          // Cut road corridor resolution
          setIsResolvingNodes(true);
          try {
            const res = await fetch('/api/resolve-nodes', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                lat1: pointA.lat,
                lng1: pointA.lng,
                lat2: lat,
                lng2: lng,
              }),
            });
            if (res.ok) {
              const data = await res.json();
              setNodeClosureResolved(data);
              setPointA((prev) => ({ ...prev, node_id: data.node_a }));
              setPointB({ lat, lng, node_id: data.node_b });
            } else {
              const errData = await res.json().catch(() => ({}));
              alert(errData.detail || 'Could not find a connecting path between selected points. Try clicking points along a connected road.');
              setPointB(null);
            }
          } catch (err) {
            console.error('Error resolving nodes:', err);
          } finally {
            setIsResolvingNodes(false);
          }
        }
      } else {
        // Reset and start new selection from this point
        setPointA({ lat, lng });
        setPointB(null);
        setNodeClosureResolved(null);
        setAddedLinkResolved(null);
      }
      return;
    }

    // Default point-to-destination live routing mode
    setOriginCoord({ lat, lng });
    try {
      const routePayload = {
        origin_lat: lat,
        origin_lng: lng,
        category: targetCategory === 'all' ? 'hospital' : targetCategory,
      };

      if (activeScenario?.params?.preset_id) {
        routePayload.preset_id = activeScenario.params.preset_id;
      } else if (activeScenario?.params?.road) {
        routePayload.road = activeScenario.params.road;
      } else if (activeScenario?.closed_edges) {
        routePayload.closed_edges = activeScenario.closed_edges;
      }

      const res = await fetch('/api/route', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(routePayload),
      });
      const data = await res.json();
      setClickedRoute(data);
    } catch (err) {
      console.error('Point routing error:', err);
    }
  };

  const handleLinkSpeedChange = (val) => {
    setLinkSpeed(val);
    if (addedLinkResolved) {
      const newTravelTime = (addedLinkResolved.distance_m / 1000.0) / Math.max(val, 1) * 60.0;
      setAddedLinkResolved((prev) => {
        let updatedComp = prev.route_comparison;
        if (updatedComp && updatedComp.normal_travel_time_min != null) {
          const timeSaved = Math.max(updatedComp.normal_travel_time_min - newTravelTime, 0);
          const pct = updatedComp.normal_travel_time_min > 0 ? (timeSaved / updatedComp.normal_travel_time_min) * 100 : 0;
          updatedComp = {
            ...updatedComp,
            link_travel_time_min: newTravelTime,
            time_saved_min: timeSaved,
            pct_faster: pct,
          };
        }
        return {
          ...prev,
          speed_kmh: val,
          travel_time_min: newTravelTime,
          route_comparison: updatedComp,
        };
      });
    }
  };

  const handleClearRoute = () => {
    setClickedRoute(null);
    setOriginCoord(null);
  };

  const handleClearNodeClosure = () => {
    setPointA(null);
    setPointB(null);
    setNodeClosureResolved(null);
    setAddedLinkResolved(null);
  };

  const handleRunNodeClosure = () => {
    if (!nodeClosureResolved || !nodeClosureResolved.closed_edges) return;
    handleRunScenario({
      scenario: 'closure',
      closed_edges: nodeClosureResolved.closed_edges,
    });
  };

  const handleRunAddLink = () => {
    if (!addedLinkResolved) return;
    const activeParams = activeScenario?.params || {};
    handleRunScenario({
      scenario: 'link',
      added_link: {
        node_a: addedLinkResolved.node_a,
        node_b: addedLinkResolved.node_b,
        speed_kmh: linkSpeed,
      },
      closed_edges: activeParams.closed_edges || activeScenario?.closed_edges,
      preset_id: activeParams.preset_id,
      road: activeParams.road,
    });
  };

  const handleReset = () => {
    setActiveScenario(null);
    setSelectedIntervention(null);
    setClickedRoute(null);
    setOriginCoord(null);
    setPointA(null);
    setPointB(null);
    setNodeClosureResolved(null);
    setAddedLinkResolved(null);
    fetchOverview(threshold, destCategory);
  };

  // Determine HUD Values
  const isDisrupted = activeScenario && activeScenario.status === 'disrupted';
  const totalPop = overview?.total_pop || 0;
  const coveredPop = isDisrupted
    ? totalPop - (activeScenario?.pop_lost_coverage || 0)
    : overview?.covered_pop || 0;
  const avgTime = isDisrupted ? activeScenario?.avg_access_after : overview?.avg_access_min || 0;
  const timeDelta = isDisrupted ? (activeScenario?.avg_access_after - activeScenario?.avg_access_before) : 0;
  const debt = isDisrupted ? activeScenario?.debt_pop_minutes : 0;
  const lostPop = isDisrupted ? activeScenario?.pop_lost_coverage : 0;

  // Map Data Setup
  const isochronesData = isDisrupted
    ? activeScenario.isochrone_sample || overview?.isochrone_sample || []
    : overview?.isochrone_sample || [];

  const closedGeoms = selectedIntervention
    ? (selectedIntervention.closed_geometries || [])
    : (activeScenario?.closed_geometries || []);

  const boostGeoms = (selectedIntervention && selectedIntervention.boost_geometries?.length)
    ? selectedIntervention.boost_geometries
    : (activeScenario?.boost_geometries || []);

  const facilityCoord = selectedIntervention?.facility_coord || activeScenario?.facility_coord || null;

  const currentAltRoute = clickedRoute || (showAltRoute ? activeScenario?.alternative_route : null);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <header className="app-header">
        <div className="logo-container">
          <div className="logo-badge">
            <Navigation size={22} color="#ffffff" />
          </div>
          <div>
            <div className="brand-title">AccessGrid AI</div>
            <div className="brand-subtitle">Emergency Urban Access Digital Twin · Mohali / Chandigarh Metro</div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          {isDisrupted ? (
            <div
              className={`badge ${activeScenario?.added_link_info ? 'badge-cyan' : 'badge-rose'}`}
              style={{
                padding: '6px 12px',
                fontSize: '0.8rem',
                borderColor: activeScenario?.added_link_info ? '#a855f7' : undefined,
                background: activeScenario?.added_link_info ? 'rgba(168, 85, 247, 0.18)' : undefined,
              }}
            >
              <span className="pulse-dot" style={{ background: activeScenario?.added_link_info ? '#c084fc' : '#f43f5e' }}></span>
              {activeScenario?.added_link_info
                ? `Temporary Link Active: ${activeScenario.scenario_title}`
                : `Disruption Active: ${activeScenario.scenario_title}`}
            </div>
          ) : (
            <div className="badge badge-emerald" style={{ padding: '6px 12px', fontSize: '0.8rem' }}>
              <span className="pulse-dot" style={{ background: '#10b981' }}></span>
              Digital Twin Online: Baseline Normal
            </div>
          )}

          {isDisrupted && (
            <button onClick={handleReset} className="btn-secondary">
              <RotateCcw size={14} /> Clear Scenario
            </button>
          )}
        </div>
      </header>

      {/* Main Cockpit */}
      <div className="app-container">
        {/* Left Control Studio */}
        <ScenarioStudio
          presets={presets}
          roads={roads}
          threshold={threshold}
          onThresholdChange={handleThresholdChange}
          destCategory={destCategory}
          onDestCategoryChange={handleDestCategoryChange}
          showAltRoute={showAltRoute}
          setShowAltRoute={setShowAltRoute}
          onRunScenario={handleRunScenario}
          onReset={handleReset}
          loading={loading}
          activeScenario={activeScenario}
          showIsochrones={showIsochrones}
          setShowIsochrones={setShowIsochrones}
          showRiskiest={showRiskiest}
          setShowRiskiest={setShowRiskiest}
          nodeClosureMode={nodeClosureMode}
          setNodeClosureMode={setNodeClosureMode}
          customToolMode={customToolMode}
          setCustomToolMode={setCustomToolMode}
          linkSpeed={linkSpeed}
          setLinkSpeed={handleLinkSpeedChange}
          pointA={pointA}
          pointB={pointB}
          nodeClosureResolved={nodeClosureResolved}
          isResolvingNodes={isResolvingNodes}
          addedLinkResolved={addedLinkResolved}
          isResolvingLink={isResolvingLink}
          onClearNodeClosure={handleClearNodeClosure}
          onRunNodeClosure={handleRunNodeClosure}
          onRunAddLink={handleRunAddLink}
        />

        {/* Center Interactive Map & Telemetry Bar */}
        <div className="map-canvas-container">
          {/* Dedicated Non-Overlapping Telemetry Bar */}
          <div className="map-telemetry-bar">
            <div className="hud-card">
              <div className="hud-label">
                <Clock size={13} color={isDisrupted ? (activeScenario?.added_link_info ? '#10b981' : 'var(--accent-rose)') : 'var(--accent-cyan)'} />
                {activeScenario?.added_link_info
                  ? '⚡ Direct Time Saved'
                  : (isDisrupted ? 'Average Delay' : 'Avg Access Time')}
              </div>
              <div className="hud-value" style={{ color: activeScenario?.added_link_info ? '#10b981' : (isDisrupted ? '#f87171' : '#ffffff'), fontSize: '1.25rem' }}>
                {activeScenario?.added_link_info
                  ? (activeScenario.added_link_info.route_comparison?.time_saved_min != null
                    ? `-${activeScenario.added_link_info.route_comparison.time_saved_min.toFixed(1)} min`
                    : `${activeScenario.added_link_info.travel_time_min?.toFixed(1)} min`)
                  : (isDisrupted
                    ? `+${(activeScenario?.per_capita_debt_min || timeDelta).toFixed(1)} min`
                    : `${avgTime?.toFixed(1)} min`)}
              </div>
              <div className={`hud-delta ${activeScenario?.added_link_info ? 'success' : (isDisrupted ? 'danger' : 'success')}`} style={{ fontSize: '0.7rem' }}>
                {activeScenario?.added_link_info
                  ? (activeScenario.added_link_info.route_comparison?.has_normal_route
                    ? `${activeScenario.added_link_info.route_comparison.pct_faster?.toFixed(0)}% faster vs normal detour`
                    : 'Restores disconnected road')
                  : (isDisrupted ? `City baseline: ${activeScenario?.avg_access_before?.toFixed(1)}m` : 'Normal City Flow')}
              </div>
            </div>

            <div className="hud-card">
              <div className="hud-label">
                <Zap size={13} color={activeScenario?.added_link_info ? 'var(--accent-emerald)' : 'var(--accent-amber)'} />
                {activeScenario?.added_link_info ? '⚡ Debt Mitigated' : (isDisrupted ? 'People Delayed' : 'Accessibility Impact')}
              </div>
              <div className="hud-value" style={{ color: activeScenario?.added_link_info ? '#10b981' : undefined, fontSize: '1.25rem' }}>
                {activeScenario?.added_link_info
                  ? (activeScenario.debt_reduced_pop_min > 0
                    ? `-${Math.round(activeScenario.debt_reduced_pop_min).toLocaleString()} m`
                    : 'Optimal')
                  : (isDisrupted ? (activeScenario?.pop_affected?.toLocaleString() || '0') : 'Optimal')}
              </div>
              <div className={`hud-delta ${activeScenario?.added_link_info ? 'success' : (isDisrupted ? 'warn' : 'success')}`} style={{ fontSize: '0.7rem' }}>
                {activeScenario?.added_link_info
                  ? (activeScenario.added_link_info.destination_impact?.avg_dest_time_saved_min > 0
                    ? `-${activeScenario.added_link_info.destination_impact.avg_dest_time_saved_min.toFixed(1)}m avg hospital gain`
                    : (activeScenario.pop_restored > 0 ? `${activeScenario.pop_restored.toLocaleString()} residents benefited` : 'Connector link active'))
                  : (isDisrupted ? `${activeScenario?.per_capita_debt_min?.toFixed(1)}m delay / resident` : '0 delays')}
              </div>
            </div>

            <div className="hud-card">
              <div className="hud-label">
                <CheckCircle2 size={13} color="var(--accent-emerald)" />
                Within 15m Window
              </div>
              <div className="hud-value" style={{ fontSize: '1.25rem' }}>
                {totalPop ? ((coveredPop / totalPop) * 100).toFixed(1) : 0}%
              </div>
              <div className="hud-delta success" style={{ fontSize: '0.7rem' }}>
                {coveredPop?.toLocaleString()} residents safe
              </div>
            </div>

            <div className="hud-card">
              <div className="hud-label">
                <ShieldAlert size={13} color="var(--accent-rose)" />
                {activeScenario?.added_link_info ? 'Remaining Debt' : 'Severe Cutoffs'}
              </div>
              <div className="hud-value" style={{ color: (lostPop > 0 || (activeScenario?.debt_pop_minutes > 0)) ? '#f87171' : '#ffffff', fontSize: '1.25rem' }}>
                {activeScenario?.added_link_info
                  ? (activeScenario.debt_pop_minutes > 0 ? `${Math.round(activeScenario.debt_pop_minutes).toLocaleString()} m` : '0 m')
                  : (lostPop ? lostPop.toLocaleString() : '0')}
              </div>
              <div className={`hud-delta ${(lostPop > 0 || (activeScenario?.debt_pop_minutes > 0)) ? 'danger' : 'success'}`} style={{ fontSize: '0.7rem' }}>
                {activeScenario?.added_link_info
                  ? (activeScenario.debt_pop_minutes > 0 ? 'Residual Accessibility Debt' : 'Full Network Coverage')
                  : (lostPop > 0 ? 'Lost Critical Care' : 'All Facilities Reachable')}
              </div>
            </div>
          </div>

          {/* Floating Map Legend */}
          <div className="floating-legend">
            <span style={{ fontWeight: '700', fontSize: '0.75rem', color: '#ffffff', marginBottom: '2px' }}>
              Travel-Time Isochrones
            </span>
            <div className="legend-item">
              <span className="legend-dot" style={{ background: '#10b981' }}></span>
              <span>&lt; 5 min (Rapid Care)</span>
            </div>
            <div className="legend-item">
              <span className="legend-dot" style={{ background: '#3b82f6' }}></span>
              <span>5–10 min (Standard Response)</span>
            </div>
            <div className="legend-item">
              <span className="legend-dot" style={{ background: '#f59e0b' }}></span>
              <span>10–15 min (Threshold Limit)</span>
            </div>
            <div className="legend-item">
              <span className="legend-dot" style={{ background: '#f97316' }}></span>
              <span>15–20 min (Delayed)</span>
            </div>
            <div className="legend-item">
              <span className="legend-dot" style={{ background: '#ef4444' }}></span>
              <span>&gt; 20 min / Isolated</span>
            </div>
          </div>

          {/* Active Intervention Preview Banner */}
          {selectedIntervention && (
            <div
              style={{
                position: 'absolute',
                top: '12px',
                left: '50%',
                transform: 'translateX(-50%)',
                zIndex: 1000,
                background: 'rgba(15, 23, 42, 0.94)',
                border: '1px solid var(--accent-cyan)',
                boxShadow: '0 8px 32px rgba(6, 182, 212, 0.3)',
                borderRadius: '8px',
                padding: '8px 16px',
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                backdropFilter: 'blur(8px)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Zap size={15} color="var(--accent-cyan)" />
                <span style={{ fontSize: '0.78rem', fontWeight: '700', color: '#ffffff' }}>
                  Preview: {selectedIntervention.name}
                </span>
              </div>
              <span className="badge badge-emerald" style={{ fontSize: '0.7rem' }}>
                -{selectedIntervention.debt_reduction_pct?.toFixed(1)}% Debt
              </span>
              <span className="badge badge-cyan" style={{ fontSize: '0.7rem' }}>
                +{selectedIntervention.population_restored?.toLocaleString()} Restored
              </span>
              <button
                onClick={() => setSelectedIntervention(null)}
                style={{
                  background: 'rgba(255,255,255,0.1)',
                  border: '1px solid rgba(255,255,255,0.15)',
                  color: '#ffffff',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '0.7rem',
                  padding: '2px 8px',
                  marginLeft: '4px',
                }}
              >
                ✕ Exit Preview
              </button>
            </div>
          )}

          {/* Leaflet Map */}
          <div className="map-wrapper">
            <MapComponent
              centre={overview?.centre}
              hospitals={overview?.hospitals || []}
              destinations={overview?.destinations || []}
              destCategory={destCategory}
              isochrones={isochronesData}
              closedGeoms={closedGeoms}
              boostGeoms={boostGeoms}
              riskiest={overview?.riskiest_corridors || []}
              facilityCoord={facilityCoord}
              alternativeRoute={currentAltRoute}
              originCoord={originCoord}
              nodeClosureMode={nodeClosureMode}
              customToolMode={customToolMode}
              pointA={pointA}
              pointB={pointB}
              previewClosureGeoms={nodeClosureResolved?.coordinates || []}
              previewLinkCoords={addedLinkResolved?.coordinates || []}
              simulatedLinkCoords={activeScenario?.added_link_geometry || []}
              addedLinkInfo={activeScenario?.added_link_info || addedLinkResolved}
              onMapClick={handleMapClick}
              onClearRoute={handleClearRoute}
              onClearNodeClosure={handleClearNodeClosure}
              showIsochrones={showIsochrones}
              showRiskiest={showRiskiest}
            />
          </div>
        </div>

        {/* Right Tabbed Analytics & AI Copilot Panel */}
        <div className="right-panel glass-panel" style={{ padding: '16px' }}>
          <div className="tab-nav">
            <button
              className={`tab-btn ${activeTab === 'surge' ? 'active' : ''}`}
              onClick={() => setActiveTab('surge')}
            >
              <Activity size={14} /> Hospital Surge
            </button>
            <button
              className={`tab-btn ${activeTab === 'interventions' ? 'active' : ''}`}
              onClick={() => setActiveTab('interventions')}
            >
              <Zap size={14} /> Interventions
            </button>
            <button
              className={`tab-btn ${activeTab === 'copilot' ? 'active' : ''}`}
              onClick={() => setActiveTab('copilot')}
            >
              <Bot size={14} /> AI Copilot
            </button>
          </div>

          {activeTab === 'surge' && (
            <HospitalSurgePanel
              surge={activeScenario?.surge || []}
              equity={activeScenario?.equity || {}}
              impact={activeScenario}
            />
          )}

          {activeTab === 'interventions' && (
            <InterventionsPanel
              candidates={activeScenario?.candidates || []}
              activeIntervention={selectedIntervention?.name}
              onSelectIntervention={(cand) => setSelectedIntervention(cand)}
              impact={activeScenario}
            />
          )}

          {activeTab === 'copilot' && (
            <CopilotPanel
              impact={activeScenario}
              candidates={activeScenario?.candidates || []}
            />
          )}
        </div>
      </div>
    </div>
  );
}
