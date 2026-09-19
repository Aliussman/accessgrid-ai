import React from 'react';
import { Award, Zap, Clock, ShieldCheck, ArrowRight } from 'lucide-react';

export default function InterventionsPanel({
  candidates = [],
  activeIntervention = null,
  onSelectIntervention,
  impact = null,
}) {
  if (!candidates || candidates.length === 0) {
    return (
      <div className="tab-content" style={{ justifyContent: 'center', alignItems: 'center', textAlign: 'center' }}>
        <ShieldCheck size={36} color="var(--accent-emerald)" style={{ marginBottom: '8px' }} />
        <h4 style={{ fontSize: '0.9rem', color: '#ffffff' }}>No Active Disruptions</h4>
        <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
          Select a disaster scenario or close a road in the Studio to compare prioritized recovery interventions.
        </p>
      </div>
    );
  }

  return (
    <div className="tab-content">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h4 style={{ fontSize: '0.85rem', fontWeight: '700', color: 'var(--text-muted)' }}>
          Tactical Intervention Ranking
        </h4>
        <span className="badge badge-emerald">{candidates.length} options evaluated</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {candidates.map((cand, idx) => {
          const isSelected = activeIntervention === cand.name;
          const isTop = idx === 0;

          return (
            <div
              key={idx}
              className={`preset-card ${isSelected ? 'active' : ''}`}
              style={{
                borderColor: isTop ? 'rgba(16, 185, 129, 0.4)' : undefined,
                background: isTop ? 'rgba(16, 185, 129, 0.08)' : undefined,
              }}
              onClick={() => onSelectIntervention(isSelected ? null : cand)}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                <span style={{ fontWeight: '700', fontSize: '0.84rem', color: '#ffffff', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  {isTop && <Award size={15} color="#34d399" />}
                  #{idx + 1} {cand.name}
                </span>
                <span className="badge badge-emerald">
                  -{cand.debt_reduction_pct?.toFixed(1)}% Debt
                </span>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '6px', fontSize: '0.72rem', color: 'var(--text-dim)', marginBottom: '8px' }}>
                <div>
                  <span style={{ display: 'block', color: 'var(--text-muted)' }}>Restored</span>
                  <strong style={{ color: '#ffffff' }}>{cand.population_restored?.toLocaleString()}</strong>
                </div>
                <div>
                  <span style={{ display: 'block', color: 'var(--text-muted)' }}>Time Saved</span>
                  <strong style={{ color: '#34d399' }}>{cand.avg_time_saved_min?.toFixed(1)} min</strong>
                </div>
                <div>
                  <span style={{ display: 'block', color: 'var(--text-muted)' }}>Score</span>
                  <strong style={{ color: 'var(--accent-cyan)' }}>{cand.score?.toFixed(0)}/100</strong>
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button
                  className={isSelected ? 'btn-primary' : 'btn-secondary'}
                  style={{ padding: '4px 10px', fontSize: '0.72rem' }}
                >
                  {isSelected ? '✓ Previewing on Map' : 'Preview Route'}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
