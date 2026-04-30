import { Lock, LockOpen } from '@phosphor-icons/react';

const FolderFormModal = ({ open, onClose, onSubmit, folderFormData, setFolderFormData, editingFolder, folders }) => {
  if (!open) return null;
  return (
    <div className="fixed inset-0 bg-black/80 overflow-y-auto z-50 p-4 sm:p-6" data-testid="folder-modal">
      <div className="bg-[#141414] border border-white/10 w-full max-w-md p-6 sm:p-8 mx-auto my-4 sm:my-8">
        <h3 className="text-3xl font-bold mb-6" style={{ fontFamily: 'Bebas Neue' }}>
          {editingFolder ? 'Edit Folder' : 'New Folder'}
        </h3>
        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Folder Name</label>
            <input data-testid="folder-name-input" type="text" value={folderFormData.name}
              onChange={(e) => setFolderFormData({ ...folderFormData, name: e.target.value })}
              className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none"
              placeholder="e.g., Season 2025-26" required />
          </div>
          <div>
            <label className="block text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3] mb-2">Parent Folder</label>
            <select data-testid="folder-parent-select"
              value={folderFormData.parent_id || ''}
              onChange={(e) => setFolderFormData({ ...folderFormData, parent_id: e.target.value || null })}
              className="w-full bg-[#0A0A0A] border border-white/10 text-white px-4 py-3 focus:border-[#007AFF] focus:outline-none">
              <option value="">None (Root level)</option>
              {folders.filter(f => f.id !== editingFolder?.id).map(f => (
                <option key={f.id} value={f.id}>{f.name}</option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-3 cursor-pointer" data-testid="folder-privacy-toggle">
            <div className={`w-10 h-6 rounded-full transition-colors relative ${folderFormData.is_private ? 'bg-[#EF4444]' : 'bg-[#39FF14]/30'}`}
              onClick={(e) => { e.preventDefault(); setFolderFormData({ ...folderFormData, is_private: !folderFormData.is_private }); }}>
              <div className={`w-4 h-4 rounded-full bg-white absolute top-1 transition-transform ${folderFormData.is_private ? 'translate-x-5' : 'translate-x-1'}`} />
            </div>
            <div className="flex items-center gap-2">
              {folderFormData.is_private ? <Lock size={16} className="text-[#EF4444]" /> : <LockOpen size={16} className="text-[#39FF14]" />}
              <span className="text-sm text-white">{folderFormData.is_private ? 'Private' : 'Public'}</span>
            </div>
          </label>
          <div className="flex gap-4 mt-6">
            <button data-testid="cancel-folder-btn" type="button" onClick={onClose}
              className="flex-1 bg-transparent border border-white/10 text-white py-3 font-bold tracking-wider uppercase hover:bg-[#1F1F1F] transition-colors">
              Cancel
            </button>
            <button data-testid="submit-folder-btn" type="submit"
              className="flex-1 bg-[#007AFF] hover:bg-[#005bb5] text-white py-3 font-bold tracking-wider uppercase transition-colors">
              {editingFolder ? 'Save' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default FolderFormModal;
