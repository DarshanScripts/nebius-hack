import { useRef } from 'react'
import saturn from '../assets/saturn.webp'
import { Icon } from './Icon'

const suggestions = [
  { label: 'Beyond Earth', topic: "What are Saturn's rings made of?" },
  { label: 'The science of sleep', topic: 'Why do we dream when we sleep?' },
  { label: 'Inside AI', topic: 'How does an artificial neural network learn?' },
]

export function NewReel({ topic, onTopic, onSubmit, busy, mock }: {
  topic: string; onTopic: (value: string) => void; onSubmit: (event: React.FormEvent) => void; busy: boolean; mock: boolean
}) {
  const input = useRef<HTMLInputElement>(null)
  const example = useRef<HTMLDialogElement>(null)
  const choose = (value: string) => { onTopic(value); input.current?.focus() }

  return <section className="creation-shell" aria-labelledby="creation-title">
    <div className="hero-copy">
      <div className="hero-intro">
        <span className="eyebrow hero-eyebrow">Research <Icon name="arrow" size={16} /> Film</span>
        <h1 id="creation-title">Ideas,<br />beautifully <em>told.</em></h1>
        <p className="hero-description">Turn any question into a research-backed<br className="wide-only" /> film with AI.</p>
        <form className="topic-form" onSubmit={onSubmit}>
          <div className="topic-input">
            <Icon name="search" />
            <label className="sr-only" htmlFor="topic">Your topic</label>
            <input ref={input} id="topic" value={topic} onChange={event => onTopic(event.target.value)}
              minLength={5} maxLength={1000} required disabled={busy} placeholder="Ask anything worth exploring…"
              autoComplete="off" aria-describedby="topic-help" />
            <button type="submit" className="create-button" aria-label={busy ? 'Creating reel' : 'Create reel'}
              disabled={busy || topic.trim().length < 5}><Icon name={busy ? 'clock' : 'arrow'} /></button>
          </div>
          <p id="topic-help" className="sr-only">Enter a question with at least five characters to create a one-minute film.</p>
        </form>
        <div className="topic-suggestions" aria-label="Topic inspiration">
          <span>A little inspiration</span>
          {suggestions.map(item => <button key={item.label} onClick={() => choose(item.topic)} disabled={busy}>{item.label}<Icon name="diagonal" size={12} /></button>)}
        </div>
        {mock && <p className="mock-hint"><span className="status-dot" />Demo workspace · sample content, no API calls</p>}
      </div>
      <footer className="hero-footer">
        <span className="workflow-caption">Research <i /> Narration <i /> Film</span>
        <span className="curiosity">Powered by curiosity <b /></span>
      </footer>
    </div>
    <div className="feature-card">
      <img className="feature-image" src={saturn} alt="An artist's view of Saturn and its luminous rings, with the Sun emerging beyond the planet" />
      <div className="feature-shade" />
      <div className="feature-top"><span><i /> A new perspective</span><span>01 — ∞</span></div>
      <button className="feature-play" onClick={() => example.current?.showModal()} aria-label="Explore Beyond Earth">
        <Icon name="play" size={26} />
      </button>
      <div className="feature-caption">
        <div><span className="eyebrow">Beyond Earth</span><h2>There’s a story<br />in every question.</h2><p>A little curiosity goes a long way.</p></div>
        <button className="feature-link" aria-label="Use the Saturn topic" onClick={() => choose(suggestions[0].topic)}><Icon name="diagonal" /></button>
      </div>
      <a className="image-credit" href="https://www.nasa.gov/image-article/view-of-rings-of-saturn/" target="_blank" rel="noreferrer">Imagery: NASA / JPL-Caltech ↗</a>
    </div>
    <dialog ref={example} className="example-dialog" aria-labelledby="example-title" onClick={event => { if (event.target === example.current) example.current.close() }}>
      <button className="dialog-close icon-button" aria-label="Close example" onClick={() => example.current?.close()}><Icon name="close" /></button>
      <img src={saturn} alt="Saturn's rings, illustrated by NASA / JPL-Caltech" />
      <div className="dialog-copy">
        <span className="eyebrow">An idea to explore</span>
        <h2 id="example-title">What are Saturn’s<br />rings made of?</h2>
        <p>Start with a question. We’ll find the research, shape a conversation, and build six scenes you can make your own.</p>
        <p className="dialog-note">Visual inspiration from NASA / JPL-Caltech. Your film is created after you submit a topic.</p>
        <button className="primary-button" onClick={() => { example.current?.close(); choose(suggestions[0].topic) }}>Use this topic <Icon name="arrow" size={18} /></button>
      </div>
    </dialog>
  </section>
}
