interface Props {
  size?: "nav" | "app" | "footer";
}

export default function BrandLogo({ size = "nav" }: Props) {
  return (
    <img
      className={`brand-logo brand-logo-${size}`}
      src={`${import.meta.env.BASE_URL}handoff-logo.png`}
      alt="Handoff"
    />
  );
}
