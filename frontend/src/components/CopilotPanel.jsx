import React, { useState, useRef, useEffect } from 'react';
import { Send, Sparkles, Download, FileText, Bot, User } from 'lucide-react';

export default function CopilotPanel({ impact = null, candidates = [] }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: 'Hello, I am the AccessGrid Emergency Logistics Copilot for the Chandigarh / Mohali metro. Run a disaster simulation or ask me about road closures, hospital triage, and priority corridors.',
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [downloadingIAP, setDownloadingIAP] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSendMessage = async (queryText) => {
    const textToSend = queryText || input;
    if (!textToSend.trim() || loading) return;

    const newMessages = [...messages, { role: 'user', content: textToSend }];
    setMessages(newMessages);
    setInput('');
    setLoading(true);

    try {
      const res = await fetch('/api/copilot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: textToSend,
          chat_history: newMessages,
          impact,
          candidates,
        }),
      });
      const data = await res.json();
      setMessages([...newMessages, { role: 'assistant', content: data.text || 'No response generated.' }]);
    } catch (err) {
      console.error('Copilot error:', err);
      setMessages([...newMessages, { role: 'assistant', content: 'Error communicating with AI Copilot service.' }]);
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadIAP = async () => {
    if (!impact) return;
    setDownloadingIAP(true);
    try {
      const res = await fetch('/api/iap', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ impact, candidates }),
      });
      const data = await res.json();

      const blob = new Blob([data.report], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `AccessGrid_Incident_Action_Plan_${new Date().toISOString().slice(0, 10)}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (err) {
      console.error('IAP download error:', err);
    } finally {
      setDownloadingIAP(false);
    }
  };

  return (
    <div className="tab-content" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* IAP Download Banner */}
      <div
        style={{
          padding: '10px 12px',
          borderRadius: 'var(--radius-md)',
          background: 'linear-gradient(135deg, rgba(14, 165, 233, 0.15), rgba(99, 102, 241, 0.15))',
          border: '1px solid rgba(56, 189, 248, 0.3)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <FileText size={16} color="var(--accent-cyan)" />
          <span style={{ fontSize: '0.78rem', fontWeight: '600', color: '#ffffff' }}>Official Incident Action Plan</span>
        </div>
        <button
          onClick={handleDownloadIAP}
          disabled={!impact || downloadingIAP}
          className="btn-primary"
          style={{ padding: '6px 10px', fontSize: '0.72rem' }}
        >
          <Download size={13} /> {downloadingIAP ? 'Exporting...' : 'Export IAP.md'}
        </button>
      </div>

      {/* Quick query chips */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
        {[
          '💰 Total Debt?',
          '🏥 Hospital Strain?',
          '⚖️ Equity Alert?',
          '⚡ Best Action?',
        ].map((chip) => (
          <button
            key={chip}
            onClick={() => handleSendMessage(chip.slice(2))}
            style={{
              padding: '4px 8px',
              borderRadius: 'var(--radius-full)',
              background: 'rgba(255, 255, 255, 0.06)',
              border: '1px solid var(--border-subtle)',
              color: 'var(--text-muted)',
              fontSize: '0.68rem',
              fontWeight: '600',
              cursor: 'pointer',
            }}
          >
            {chip}
          </button>
        ))}
      </div>

      {/* Chat Messages */}
      <div className="chat-history" style={{ flex: 1, minHeight: '220px' }}>
        {messages.map((m, idx) => (
          <div key={idx} className={`chat-bubble ${m.role}`}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px', fontSize: '0.68rem', color: 'var(--text-dim)' }}>
              {m.role === 'assistant' ? <Bot size={12} color="var(--accent-cyan)" /> : <User size={12} color="#ffffff" />}
              <span>{m.role === 'assistant' ? 'Logistics Copilot' : 'Planner'}</span>
            </div>
            <div style={{ whiteSpace: 'pre-wrap', color: '#ffffff' }}>{m.content}</div>
          </div>
        ))}
        {loading && (
          <div className="chat-bubble assistant" style={{ fontStyle: 'italic', color: 'var(--text-dim)' }}>
            <Sparkles size={14} className="pulse-dot" style={{ marginRight: '6px' }} />
            Analyzing emergency network logistics...
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Chat Input */}
      <div className="chat-input-area">
        <input
          type="text"
          className="chat-input"
          placeholder="Ask a tactical emergency question..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
          disabled={loading}
        />
        <button className="btn-primary" onClick={() => handleSendMessage()} disabled={loading || !input.trim()}>
          <Send size={15} />
        </button>
      </div>
    </div>
  );
}
