const range = (n) => Array.from({ length: n }, (_, i) => i)

function Bone({ className = '', style, delay = 0 }) {
  return (
    <div
      className={`bone ${className}`}
      style={delay ? { ...style, animationDelay: `${delay}ms` } : style}
      aria-hidden="true"
    />
  )
}

function SkeletonTile({ delay }) {
  return <Bone className="bone-tile" delay={delay} />
}

export function RowSkeleton({ tiles = 7, offset = 0 }) {
  return (
    <section className="row">
      <Bone className="bone-heading" delay={offset} />
      <div className="row-strip bone-strip">
        {range(tiles).map((i) => (
          <SkeletonTile key={i} delay={offset + i * 90} />
        ))}
      </div>
    </section>
  )
}

export function BrowseSkeleton({ hero = true }) {
  return (
    <div role="status" aria-label="Loading">
      {hero && (
        <section className="hero bone-hero">
          <div className="hero-body">
            <Bone className="bone-title" />
            <Bone className="bone-line short" />
            <Bone className="bone-line" />
            <Bone className="bone-line" />
            <div className="hero-actions">
              <Bone className="bone-button" />
              <Bone className="bone-button" />
            </div>
          </div>
        </section>
      )}
      <div className="rows">
        {range(4).map((i) => (
          <RowSkeleton key={i} offset={i * 120} />
        ))}
      </div>
    </div>
  )
}

export function GridSkeleton({ count = 18 }) {
  return (
    <div className="grid" role="status" aria-label="Loading">
      {range(count).map((i) => (
        <SkeletonTile key={i} delay={(i % 6) * 90 + Math.floor(i / 6) * 120} />
      ))}
    </div>
  )
}

export function EpisodesSkeleton({ count = 4 }) {
  return (
    <div role="status" aria-label="Loading">
      {range(count).map((i) => (
        <div className="episode" key={i}>
          <Bone className="episode-still" delay={i * 110} />
          <div className="episode-text">
            <Bone className="bone-line half" delay={i * 110} />
            <Bone className="bone-line tiny" delay={i * 110} />
            <Bone className="bone-line" delay={i * 110} />
            <Bone className="bone-line short" delay={i * 110} />
          </div>
          <span />
        </div>
      ))}
    </div>
  )
}

export function DetailSkeleton() {
  return (
    <div className="sheet-body" role="status" aria-label="Loading">
      <Bone className="bone-line tiny" />
      <div className="sheet-actions">
        <Bone className="bone-button" />
        <div className="rate">
          {range(4).map((i) => <Bone key={i} className="bone-round" delay={i * 60} />)}
        </div>
      </div>
      <div className="sheet-info">
        <div>
          <Bone className="bone-line half" />
          <Bone className="bone-line" />
          <Bone className="bone-line" />
          <Bone className="bone-line short" />
        </div>
        <div>
          <Bone className="bone-line" />
          <Bone className="bone-line short" />
          <Bone className="bone-line half" />
        </div>
      </div>
      <Bone className="bone-heading" />
      <EpisodesSkeleton count={3} />
    </div>
  )
}

export function DownloadsSkeleton({ count = 5 }) {
  return (
    <div className="bone-table" role="status" aria-label="Loading">
      {range(count).map((i) => (
        <div className="bone-table-row" key={i}>
          <Bone className="bone-poster" delay={i * 100} />
          <div className="bone-table-text">
            <Bone className="bone-line half" delay={i * 100} />
            <Bone className="bone-line short" delay={i * 100} />
          </div>
          <Bone className="bone-line tiny" delay={i * 100} />
          <Bone className="bone-line tiny" delay={i * 100} />
        </div>
      ))}
    </div>
  )
}
