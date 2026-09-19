import React, { useState } from 'react';
import { Activity, Users, ShieldAlert, HeartPulse, AlertOctagon, CheckCircle2, Filter } from 'lucide-react';

export default function HospitalSurgePanel({ surge = [], equity = {}, impact = null }) {
  const [filterMode, setFilterMode] = useState('impacted'); // 'impacted' | 'all'
  const dispro = equity?.disproportionately_affected || [];

  const groups = [
    { key: 'general', label: 'General Population', icon: Users, color: '#3b82f6' },
    { key: 'elderly', label: 'Elderly (65+)', icon: HeartPulse, color: '#f59e0b' },
    { key: 'mobility', label: 'Mobility-Limited', icon: ShieldAlert, color: '#ec4899' },
    { key: 'lowcar', label: 'Low-Car Households', icon: Activity, color: '#8b5cf6' },
  ];

  // Filter hospitals: severed access (<0) or critical surge (>0)
  const impactedHospitals = surge.filter(
    (h) => h.status !== 'STABLE' || Math.abs(h.delta_pop) > 500
  );

  const displayedHospitals = filterMode === 'impacted' ? impactedHospitals : surge;

  // Calculate affected zone delay per group if available
  const perCapitaDelay = impact?.per_capita_debt_min || 0;

  return (
    <div className="tab-content">
      {/* Equity Alert banner */}
      {dispro.length > 0 && (
        <div
          style={{
            padding: '12px 14px',
            borderRadius: 'var(--radius-md)',
            background: 'rgba(244, 63, 94, 0.12)',
            border: '1px solid rgba(244, 63, 94, 0.35)',
            display: 'flex',
            gap: '10px',
            alignItems: 'flex-start',
          }}
        >
          <AlertOctagon size={18} color="#f43f5e" style={{ flexShrink: 0, marginTop: '2px' }} />
          <div>
            <span style={{ fontSize: '0.8rem', fontWeight: '700', color: '#fda4af', display: 'block' }}>
              ⚠️ Disproportionate Demographic Impact
            </span>
            <span style={{ fontSize: '0.74rem', color: '#fecdd3', lineHeight: '1.4' }}>
              Vulnerable groups ({dispro.join(', ')}) suffer disproportionately higher travel delays than the general population.
            </span>
          </div>
        </div>
      )}

      {/* Demographic Equity Cards */}
      <div>
        <h4 style={{ fontSize: '0.85rem', fontWeight: '700', marginBottom: '8px', color: 'var(--text-muted)' }}>
          Demographic Vulnerability Breakdown
        </h4>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px' }}>
          {groups.map(({ key, label, icon: Icon, color }) => {
            const data = equity[key] || {};
            const cityDelta = data.delta_min || 0;
            const lost = data.pop_lost_coverage || 0;
            // Highlight affected delay if disrupted
            const displayDelay = impact ? (perCapitaDelay > 0 ? perCapitaDelay : cityDelta) : 0;

            return (
              <div
                key={key}
                style={{
                  padding: '10px 12px',
                  borderRadius: 'var(--radius-md)',
                  background: 'rgba(18, 26, 44, 0.7)',
                  border: '1px solid var(--border-subtle)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                  <Icon size={14} color={color} />
                  <span style={{ fontSize: '0.72rem', fontWeight: '600', color: 'var(--text-muted)' }}>
                    {label}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <span style={{ fontSize: '1.05rem', fontWeight: '700', color: displayDelay > 0 ? '#f87171' : '#ffffff' }}>
                    {displayDelay > 0 ? `+${displayDelay.toFixed(1)}m` : `0.0m`}
                  </span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>
                    {lost > 0 ? `${lost.toLocaleString()} lost` : '0 lost'}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <hr style={{ borderColor: 'var(--border-subtle)' }} />

      {/* Hospital Surge & Inaccessible Hospitals Header */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <h4 style={{ fontSize: '0.85rem', fontWeight: '700', color: 'var(--text-muted)', margin: 0 }}>
            🏥 Hospital Access & Surge Strain
          </h4>

          {/* Concise Filter Toggle */}
          <div style={{ display: 'flex', gap: '4px' }}>
            <button
              onClick={() => setFilterMode('impacted')}
              style={{
                fontSize: '0.68rem',
                fontWeight: '600',
                padding: '3px 8px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid',
                borderColor: filterMode === 'impacted' ? 'var(--accent-cyan)' : 'var(--border-subtle)',
                background: filterMode === 'impacted' ? 'rgba(14, 165, 233, 0.2)' : 'transparent',
                color: filterMode === 'impacted' ? '#ffffff' : 'var(--text-dim)',
                cursor: 'pointer',
              }}
            >
              Inaccessible / Strained ({impactedHospitals.length})
            </button>
            <button
              onClick={() => setFilterMode('all')}
              style={{
                fontSize: '0.68rem',
                fontWeight: '600',
                padding: '3px 8px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid',
                borderColor: filterMode === 'all' ? 'var(--accent-cyan)' : 'var(--border-subtle)',
                background: filterMode === 'all' ? 'rgba(14, 165, 233, 0.2)' : 'transparent',
                color: filterMode === 'all' ? '#ffffff' : 'var(--text-dim)',
                cursor: 'pointer',
              }}
            >
              All ({surge.length})
            </button>
          </div>
        </div>

        {/* Hospital Cards List */}
        {displayedHospitals.length === 0 ? (
          <div
            style={{
              padding: '16px',
              textAlign: 'center',
              borderRadius: 'var(--radius-md)',
              background: 'rgba(16, 185, 129, 0.08)',
              border: '1px solid rgba(16, 185, 129, 0.25)',
            }}
          >
            <CheckCircle2 size={24} color="#34d399" style={{ marginBottom: '6px' }} />
            <p style={{ fontSize: '0.78rem', color: '#ffffff', fontWeight: '600', margin: 0 }}>
              All Hospitals Accessible
            </p>
            <p style={{ fontSize: '0.72rem', color: 'var(--text-dim)', margin: '4px 0 0 0' }}>
              No severed hospital access or critical surge overloads in this scenario.
            </p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {displayedHospitals.map((h, idx) => {
              const isSurge = h.status === 'CRITICAL SURGE' || h.delta_pop > 1000;
              const isCutOff = h.status === 'CUT OFF' || h.delta_pop < -300;

              return (
                <div
                  key={idx}
                  style={{
                    padding: '10px 12px',
                    borderRadius: 'var(--radius-md)',
                    background: 'rgba(18, 26, 44, 0.7)',
                    border: '1px solid',
                    borderColor: isCutOff
                      ? 'rgba(239, 68, 68, 0.5)'
                      : isSurge
                      ? 'rgba(245, 158, 11, 0.4)'
                      : 'var(--border-subtle)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                    <span style={{ fontWeight: '700', fontSize: '0.82rem', color: '#ffffff' }}>{h.name}</span>
                    <span className={`badge ${isCutOff ? 'badge-rose' : isSurge ? 'badge-amber' : 'badge-emerald'}`}>
                      {h.badge}
                    </span>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'var(--text-dim)' }}>
                    <span>Capacity: {h.capacity_beds} beds</span>
                    <span style={{ fontWeight: '600', color: isCutOff ? '#f87171' : isSurge ? '#fbbf24' : '#34d399' }}>
                      {h.delta_pop < 0
                        ? `Access Lost: ${h.delta_pop.toLocaleString()} (${h.delta_pct.toFixed(1)}%)`
                        : `Patient Surge: +${h.delta_pop.toLocaleString()} (${h.delta_pct.toFixed(1)}%)`}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
