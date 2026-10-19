export function LogoMark({ className }: { className?: string }) {
  return (
    <img
      src="/logo.png"
      alt="AeroGrid AI Logo"
      className={className}
      style={{ objectFit: 'contain' }}
    />
  )
}
