const CreateMatchModal = ({ open, onClose, onSubmit, formData, setFormData, loading }) => {
  if (!open) return null;
  return (
    <div className="fixed inset-0 bg-black/80 overflow-y-auto z-50 p-4 sm:p-6" data-testid="create-match-modal">
      <div className="bg-[#141414] border border-white/10 w-full max-w-lg p-6 sm:p-8 mx-auto my-4 sm:my-8">
        <h3 className="text-3xl font-bold mb-6" style={{ fontFamily: 'Bebas Neue' }}>Create New Match</h3>
        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Home Team</label>
            <input data-testid="home-team-input" type="text" value={formData.team_home}
              onChange={(e) => setFormData({ ...formData, team_home: e.target.value })}
              className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none" required />
          </div>
          <div>
            <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Away Team</label>
            <input data-testid="away-team-input" type="text" value={formData.team_away}
              onChange={(e) => setFormData({ ...formData, team_away: e.target.value })}
              className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none" required />
          </div>
          <div>
            <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Date</label>
            <input data-testid="match-date-input" type="date" value={formData.date}
              onChange={(e) => setFormData({ ...formData, date: e.target.value })}
              className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none" required />
          </div>
          <div>
            <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Competition</label>
            <input data-testid="competition-input" type="text" value={formData.competition}
              onChange={(e) => setFormData({ ...formData, competition: e.target.value })}
              className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none"
              placeholder="e.g., Premier League, Champions League" />
          </div>
          <div className="flex gap-4 mt-6">
            <button data-testid="cancel-create-btn" type="button" onClick={onClose}
              className="flex-1 bg-transparent border border-white/10 text-white py-3 font-bold tracking-wider uppercase hover:bg-[#1F1F1F] transition-colors">
              Cancel
            </button>
            <button data-testid="submit-create-btn" type="submit" disabled={loading}
              className="flex-1 bg-[#007AFF] hover:bg-[#005bb5] text-white py-3 font-bold tracking-wider uppercase transition-colors disabled:opacity-50">
              {loading ? 'Creating...' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default CreateMatchModal;
