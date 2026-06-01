import '../../styles/logo-intro.css';

/**
 * Branded S11 loading state shown in the dashboard content area while the
 * first matches fetch is in flight. Prevents the "Welcome" empty-state flash
 * right after login and gives a polished, on-brand transition moment.
 */
const DashboardLoader = () => (
  <div
    data-testid="dashboard-loader"
    className="flex flex-col items-center justify-center py-28 sm:py-36"
  >
    <img
      src="/logo-mark-256.png"
      alt="Soccer Scout 11"
      className="h-14 sm:h-16 w-auto ss11-loader-mark"
    />
    <div className="mt-7 w-44 h-[3px] bg-white/10 overflow-hidden rounded-full">
      <div className="h-full w-1/3 bg-[#007AFF] rounded-full ss11-loader-bar" />
    </div>
    <p className="mt-5 text-[#6B7280] text-xs tracking-[0.3em] uppercase">
      Loading your match library
    </p>
  </div>
);

export default DashboardLoader;
