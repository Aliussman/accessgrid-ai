import React from 'react';
import { Award, Zap, Clock, ShieldCheck, Target, HeartPulse, GitFork, Globe, Layers, CheckCircle2 } from 'lucide-react';

export default function InterventionsPanel({
  candidates = [],
  activeIntervention = null,
  onSelectIntervention,
  impact = null,
}) {
  if (!candidates || candidates.length === 0) {
    return (
      <div className="tab-content" style={{ justifyContent: 'center', alignItems: 'center', textAlign: 'center', padding: '32px 16px' }}>
        <ShieldCheck size={38} color="var(--accent-emerald)" style={{ marginBottom: '10px' }} />
        <h4 style={{ fontSize: '0.92rem', color: '#ffffff', marginBottom: '6px' }}>No Active Disruptions</h4>
        <p style={{ fontSize: '0.76rem', color: 'var(--text-dim)', lineHeight: '1.4' }}>
          Select a disaster scenario or simulate a road closure in the Studio to evaluate and rank tactical recovery interventions.
        </p>
      </div>
    );
  }

  const getCategoryIcon = (category) => {
    switch (category) {
      case 'Chokepoint Clearance':
        return <Target size={13} color="#f59e0b" />;
      case 'Green-Wave EMS Corridor':
        return <Zap size={13} color="#10b981" />;
      case 'Mobile Triage Unit':
        return <HeartPulse size={13} color="#c084fc" />;
      case 'Phased Corridor Recovery':
        return <GitFork size={13} color="#38bdf8" />;
      case 'Full Network Recovery':
        return <Globe size={13} color="#94a3b8" />;
      default:
        return <Layers size={13} color="#38bdf8" />;
    }
  };

  const getCategoryBadgeClass = (category) => {
    switch (category) {
      case 'Chokepoint Clearance':
        return 'badge-amber';
      case 'Green-Wave EMS Corridor':
        return 'badge-emerald';
      case 'Mobile Triage Unit':
        return 'badge-purple';
      case 'Phased Corridor Recovery':
        return 'badge-cyan';
      default:
        return 'badge-slate';
    }
  };

  return (
    <div className="tab-content">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
        <div>
          <h4 style={{ fontSize: '0.85rem', fontWeight: '700', color: 'var(--text-muted)', margin: 0 }}>
            Tactical Intervention Ranking
          </h4>
          <span style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>
            Ranked by multi-criteria recovery yield vs resource effort
          </span>
        </div>
        <span className="badge badge-emerald">{candidates.length} options evaluated</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '6px' }}>
        {candidates.map((cand, idx) => {
          const isSelected = activeIntervention === cand.name;
          const isTop = idx === 0;

          return (
            <div
              key={idx}
              className={`preset-card ${isSelected ? 'active' : ''}`}
              style={{
                borderColor: isSelected
                  ? 'var(--accent-cyan)'
                  : isTop
                  ? 'rgba(16, 185, 129, 0.4)'
                  : 'rgba(255, 255, 255, 0.07)',
                background: isSelected
                  ? 'rgba(6, 182, 212, 0.12)'
                  : isTop
                  ? 'rgba(16, 185, 129, 0.07)'
                  : 'rgba(255, 255, 255, 0.03)',
                padding: '12px',
                borderRadius: '8px',
                transition: 'all 0.15s ease-in-out',
                cursor: 'pointer',
              }}
              onClick={() => onSelectIntervention(isSelected ? null : cand)}
            >
              {/* Top Row: Category & Badges */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px', flexWrap: 'wrap', gap: '4px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span
                    className={`badge ${getCategoryBadgeClass(cand.category)}`}
                    style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.68rem', padding: '2px 7px' }}
                  >
                    {getCategoryIcon(cand.category)}
                    {cand.category || 'Tactical Option'}
                  </span>
                  {cand.effort && (
                    <span
                      style={{
                        fontSize: '0.66rem',
                        color: 'var(--text-dim)',
                        background: 'rgba(255,255,255,0.05)',
                        padding: '2px 6px',
                        borderRadius: '4px',
                        border: '1px solid rgba(255,255,255,0.08)',
                      }}
                    >
                      {cand.effort}
                    </span>
                  )}
                </div>

                <span className="badge badge-emerald" style={{ fontWeight: '700', fontSize: '0.72rem' }}>
                  -{cand.debt_reduction_pct?.toFixed(1)}% Debt
                </span>
              </div>

              {/* Title */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                {isTop && <Award size={15} color="#34d399" style={{ flexShrink: 0 }} />}
                <span style={{ fontWeight: '700', fontSize: '0.84rem', color: '#ffffff', lineHeight: '1.3' }}>
                  #{idx + 1} {cand.name}
                </span>
              </div>

              {/* Actionable Tactic Description */}
              {cand.tactic && (
                <p
                  style={{
                    fontSize: '0.72rem',
                    color: '#94a3b8',
                    lineHeight: '1.35',
                    margin: '4px 0 8px',
                    padding: '4px 8px',
                    background: 'rgba(0,0,0,0.2)',
                    borderRadius: '4px',
                    borderLeft: '2px solid rgba(56, 189, 248, 0.4)',
                  }}
                >
                  {cand.tactic}
                </p>
              )}

              {/* Metrics Grid */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(3, 1fr)',
                  gap: '6px',
                  fontSize: '0.72rem',
                  color: 'var(--text-dim)',
                  marginBottom: '8px',
                  background: 'rgba(255,255,255,0.02)',
                  padding: '6px 8px',
                  borderRadius: '6px',
                }}
              >
                <div>
                  <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: '0.66rem' }}>Restored</span>
                  <strong style={{ color: '#ffffff', fontSize: '0.8rem' }}>
                    {cand.population_restored?.toLocaleString() || 0}
                  </strong>
                </div>
                <div>
                  <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: '0.66rem' }}>Time Saved</span>
                  <strong style={{ color: '#34d399', fontSize: '0.8rem' }}>
                    {cand.avg_time_saved_min > 0 ? `+${cand.avg_time_saved_min.toFixed(1)}m` : '0m'}
                  </strong>
                </div>
                <div>
                  <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: '0.66rem' }}>Priority Score</span>
                  <strong style={{ color: 'var(--accent-cyan)', fontSize: '0.8rem' }}>
                    {cand.score?.toFixed(0)}/100
                  </strong>
                </div>
              </div>

              {/* Action Button */}
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button
                  className={isSelected ? 'btn-primary' : 'btn-secondary'}
                  style={{ padding: '4px 10px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '4px' }}
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelectIntervention(isSelected ? null : cand);
                  }}
                >
                  {isSelected ? (
                    <>
                      <CheckCircle2 size={12} /> Previewing on Map
                    </>
                  ) : (
                    'Preview Strategy on Map'
                  )}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
