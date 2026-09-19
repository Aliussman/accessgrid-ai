import React from 'react';
import { Activity, Users, ShieldAlert, HeartPulse, AlertOctagon, CheckCircle2 } from 'lucide-react';

export default function HospitalSurgePanel({ surge = [], equity = {}, impact = null }) {
  const dispro = equity?.disproportionately_affected || [];
  const groups = [
    { key: 'general', label: 'General Population', icon: Users, color: '#3b82f6' },
    { key: 'elderly', label: 'Elderly (65+)', icon: HeartPulse, color: '#f59e0b' },
    { key: 'mobility', label: 'Mobility-Limited', icon: ShieldAlert, color: '#ec4899' },
    { key: 'lowcar', label: 'Low-Car Households', icon: Activity, color: '#8b5cf6' },
  ];

  return (
    <div className="tab-content">
      {/* Equity Alert banner */}
      {dispro.length > 0 && (
        <div style={{
          padding: '12px 14px',
          borderRadius: 'var(--radius-md)',
          background: 'rgba(244, 63, 94, 0.12)',
          border: '1px solid rgba(244, 63, 94, 0.35)',
          display: 'flex',
          gap: '10px',
          alignItems: 'flex-start'
        }}>
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
            const delta = data.delta_min || 0;
            const lost = data.pop_lost_coverage || 0;

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
                  <span style={{ fontSize: '1.05rem', fontWeight: '700', color: delta > 0 ? '#f87171' : '#ffffff' }}>
                    {delta > 0 ? `+${delta.toFixed(1)}m` : `${delta.toFixed(1)}m`}
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

      {/* Hospital Surge & Capacity Triage */}
      <div>
        <h4 style={{ fontSize: '0.85rem', fontWeight: '700', marginBottom: '8px', color: 'var(--text-muted)' }}>
          🏥 Hospital Capacity & Surge Strain
        </h4>
        {surge.length === 0 ? (
          <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>No active surge data.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {surge.map((h, idx) => {
              const isSurge = h.delta_pop > 0;
              const isCutOff = h.delta_pop < -300;

              return (
                <div
                  key={idx}
                  style={{
                    padding: '10px 12px',
                    borderRadius: 'var(--radius-md)',
                    background: 'rgba(18, 26, 44, 0.7)',
                    border: '1px solid',
                    borderColor: isSurge
                      ? 'rgba(239, 68, 68, 0.35)'
                      : isCutOff
                      ? 'rgba(245, 158, 11, 0.3)'
                      : 'var(--border-subtle)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                    <span style={{ fontWeight: '700', fontSize: '0.82rem', color: '#ffffff' }}>{h.name}</span>
                    <span className={`badge ${isSurge ? 'badge-rose' : isCutOff ? 'badge-amber' : 'badge-emerald'}`}>
                      {h.badge}
                    </span>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'var(--text-dim)' }}>
                    <span>Capacity: {h.capacity_beds} beds</span>
                    <span style={{ fontWeight: '600', color: isSurge ? '#f87171' : isCutOff ? '#fbbf24' : '#34d399' }}>
                      Patient Shift: {h.delta_pop > 0 ? `+${h.delta_pop.toLocaleString()}` : h.delta_pop.toLocaleString()} ({h.delta_pct.toFixed(1)}%)
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
