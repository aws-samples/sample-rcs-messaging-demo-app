import type { CSSProperties } from 'react';
import type { RcsCardContent, RcsMessage, RcsSuggestion } from '../api';

// A lightweight, CSS-only phone-mockup renderer for RCS message content.
//
// This is not a pixel-accurate simulation of any messaging app, but it is
// deliberately *platform-specific*, because the two platforms do not render the
// same payload the same way. Verified on hardware (2026-09-14, one testing
// agent, iOS 18+ and Android with RCS enabled):
//
//                     | Android                     | iOS 18+
//   ------------------|-----------------------------|---------------------------
//   carousel          | horizontal swipe strip      | paged stack, "1 of n"
//   card Suggestions  | full-width buttons INSIDE    | separate chip bubbles
//                     | the card                    | BELOW the card
//   message-level     | outlined pills, right-       | chip bubbles
//   Suggestions       | aligned                     |
//   theme             | dark (as observed)          | light
//   composer label    | "RCS message"               | "Text Message • RCS"
//   agent header      | back, logo, name, overflow  | logo over a tappable
//                     |                             | name pill
//   thread notice     | "This is an RCS for         | none
//                     | Business chat."             |
//
// The card-suggestion difference is the one that matters for content design:
// on Android the chips read as part of the card, on iOS they detach. A single
// mockup cannot be honest about both, which is why this component takes a
// platform rather than splitting the difference.
//
// Content itself IS accurate on either setting: it's the exact payload the real
// send path would use, rendered from lambda/flows/*.py via GET
// /api/vignettes/preview (see PhonePreviewPopover for how it's fetched).
export type Platform = 'ios' | 'android';

export default function PhonePreview({
  messages,
  platform,
  agentName,
  logoUrl,
}: {
  messages: RcsMessage[];
  platform: Platform;
  agentName: string;
  logoUrl?: string;
}) {
  const t = platform === 'ios' ? iosTheme : androidTheme;
  return (
    <div style={frameStyle}>
      {/* Scrolling regions inside the frame really do scroll -- the thread
          vertically, an Android carousel horizontally -- but no handset draws a
          scrollbar over the conversation, and the browser's default one reads as
          part of the mockup. Hide the chrome, keep the behaviour. Inline styles
          can't express ::-webkit-scrollbar, hence the style element. */}
      <style>{NO_SCROLLBAR_CSS}</style>
      <div style={{ ...screenStyle, background: t.screenBg }}>
        <div style={{ ...statusBarStyle, color: t.dimText }}>
          <span>{platform === 'ios' ? '9:41' : '12:15'}</span>
          <span>▁▄▆ ᯤ 100</span>
        </div>
        <AgentHeader platform={platform} theme={t} agentName={agentName} logoUrl={logoUrl} />
        <div className="rcs-preview-scroll" style={chatAreaStyle}>
          {/* Google inserts this on Android and it is not configurable. Part of
              what a recipient sees, so it belongs in an honest mockup. */}
          {platform === 'android' && (
            <div style={{ ...noticeStyle, color: t.dimText }}>This is an RCS for Business chat.</div>
          )}
          {messages.map((m, i) => (
            <MessageBlock key={i} message={m} platform={platform} theme={t} />
          ))}
        </div>
        <div style={{ ...composerStyle, background: t.composerBg, color: t.dimText }}>
          <span>＋</span>
          <span style={{ flex: 1 }}>{platform === 'ios' ? 'Text Message • RCS' : 'RCS message'}</span>
        </div>
      </div>
    </div>
  );
}

// The agent identity strip. Logo and display name render on both platforms;
// neither shows a verified badge on a testing agent, so this deliberately
// renders none. See Settings -> "Brand identity: testing vs production".
function AgentHeader({
  platform,
  theme: t,
  agentName,
  logoUrl,
}: {
  platform: Platform;
  theme: Theme;
  agentName: string;
  logoUrl?: string;
}) {
  // iOS draws a larger avatar because it sits alone above the name; Android's is
  // inline in the app bar. Both are CIRCULAR -- that is not a stylistic choice
  // here, it is what the handsets do to the 224x224 square you upload, which is
  // why the registration wants a PNG with alpha. `contain` rather than `cover`
  // so a logo designed inside the inscribed circle isn't cropped further.
  const size = platform === 'ios' ? 30 : 22;
  const logo = logoUrl ? (
    <img
      src={logoUrl}
      alt=""
      style={{ width: size, height: size, borderRadius: '50%', objectFit: 'contain', background: t.logoFallbackBg }}
    />
  ) : (
    <div style={{ ...logoFallbackStyle, width: size, height: size, background: t.logoFallbackBg, color: t.text }}>
      {(agentName || '?').slice(0, 1).toUpperCase()}
    </div>
  );

  if (platform === 'android') {
    // Back arrow, logo, name, overflow menu -- a conventional app bar.
    return (
      <div style={{ ...headerRowStyle, borderBottom: `1px solid ${t.border}`, color: t.text }}>
        <span style={{ fontSize: 13 }}>←</span>
        {logo}
        <span style={{ fontSize: 11.5, fontWeight: 600, flex: 1 }}>{agentName}</span>
        <span style={{ fontSize: 13 }}>⋮</span>
      </div>
    );
  }
  // iOS centres the logo above a tappable name pill; the chevron is the tap
  // target for the agent info sheet, which is where iOS puts "Verified by
  // Google".
  return (
    <div
      style={{
        ...headerColStyle,
        borderBottom: `1px solid ${t.border}`,
        color: t.text,
      }}
    >
      {logo}
      <span style={{ ...namePillStyle, background: t.pillBg }}>{agentName} ›</span>
    </div>
  );
}

function MessageBlock({
  message,
  platform,
  theme: t,
}: {
  message: RcsMessage;
  platform: Platform;
  theme: Theme;
}) {
  const content = message.Content;
  if (!content) return null;

  // Message-level suggestions are separate from the card on both platforms;
  // only their shape differs, which SuggestionRow handles.
  const messageSuggestions = message.Suggestions && (
    <SuggestionRow suggestions={message.Suggestions} platform={platform} theme={t} level="message" />
  );

  if (content.TextMessage) {
    return (
      <div style={bubbleWrapStyle}>
        <div style={{ ...bubbleStyle, background: t.bubbleBg, border: `1px solid ${t.border}`, color: t.text }}>
          {content.TextMessage.Body}
        </div>
        {messageSuggestions}
      </div>
    );
  }

  if (content.RichCard) {
    return (
      <div style={bubbleWrapStyle}>
        <RichCard card={content.RichCard.CardContent} platform={platform} theme={t} />
        {messageSuggestions}
      </div>
    );
  }

  if (content.Carousel) {
    const cards = content.Carousel.CardContents;
    // The 90% bubble cap doesn't apply to an Android carousel: the strip runs to
    // the edge of the thread, which is what puts the next card's leading edge
    // right at the frame and makes it read as swipeable.
    return (
      <div style={platform === 'android' ? carouselWrapStyle : bubbleWrapStyle}>
        {platform === 'android' ? (
          // Horizontal swipe strip: the next card peeks in from the right.
          <div className="rcs-preview-scroll" style={carouselStripStyle}>
            {cards.map((card, i) => (
              <div key={i} style={carouselCardStyle}>
                <RichCard card={card} platform={platform} theme={t} compact />
              </div>
            ))}
          </div>
        ) : (
          // iOS pages the carousel: one card at a time under a "1 of n"
          // indicator. Showing only the first card is the accurate render --
          // the rest are a swipe away, not on screen.
          <>
            <RichCard card={cards[0]} platform={platform} theme={t} compact />
            <div style={{ ...pagerStyle, color: t.dimText }}>▤ 1 of {cards.length}</div>
          </>
        )}
        {messageSuggestions}
      </div>
    );
  }

  return null;
}

function RichCard({
  card,
  platform,
  theme: t,
  compact,
}: {
  card: RcsCardContent;
  platform: Platform;
  theme: Theme;
  compact?: boolean;
}) {
  // The whole point of the split: Android draws card suggestions as buttons
  // inside the card, iOS detaches them into bubbles underneath it.
  const cardSuggestions = card.Suggestions && (
    <SuggestionRow suggestions={card.Suggestions} platform={platform} theme={t} level="card" />
  );

  const body = (
    <div style={{ ...cardStyle, background: t.cardBg, border: `1px solid ${t.border}` }}>
      {card.Media?.FileUrl && (
        <img
          src={card.Media.FileUrl}
          alt=""
          style={compact ? cardImageCompactStyle : cardImageStyle}
        />
      )}
      <div style={{ padding: '10px 12px' }}>
        {card.Title && <div style={{ ...cardTitleStyle, color: t.text }}>{card.Title}</div>}
        {card.Description && <div style={{ ...cardDescStyle, color: t.dimText }}>{card.Description}</div>}
        {platform === 'android' && cardSuggestions}
      </div>
    </div>
  );

  if (platform === 'android') return body;
  return (
    <>
      {body}
      {cardSuggestions}
    </>
  );
}

function SuggestionRow({
  suggestions,
  platform,
  theme: t,
  level,
}: {
  suggestions: RcsSuggestion[];
  platform: Platform;
  theme: Theme;
  level: 'card' | 'message';
}) {
  // Android card suggestions are stacked full-width buttons; everything else
  // is an inline row of chips. Android message-level chips sit right-aligned.
  const androidCardButtons = platform === 'android' && level === 'card';
  const rowStyle: CSSProperties = androidCardButtons
    ? { display: 'flex', flexDirection: 'column', gap: 4, marginTop: 8 }
    : {
        display: 'flex',
        flexWrap: 'wrap',
        gap: 6,
        marginTop: 8,
        justifyContent: platform === 'android' ? 'flex-end' : 'flex-start',
      };

  return (
    <div style={rowStyle}>
      {suggestions.map((s, i) => {
        const label = suggestionLabel(s);
        if (!label) return null;
        if (androidCardButtons) {
          return (
            <span key={i} style={{ ...cardButtonStyle, background: t.buttonBg, color: t.linkText }}>
              {label}
            </span>
          );
        }
        return (
          <span
            key={i}
            style={
              platform === 'ios'
                ? { ...iosChipBubbleStyle, background: t.bubbleBg, color: t.linkText, border: `1px solid ${t.border}` }
                : { ...chipStyle, border: `1px solid ${t.chipBorder}`, color: t.linkText }
            }
          >
            {label}
          </span>
        );
      })}
    </div>
  );
}

function suggestionLabel(s: RcsSuggestion): string | null {
  if (s.Reply) return s.Reply.Text;
  if (s.OpenUrl) return s.OpenUrl.Text;
  if (s.DialPhone) return `📞 ${s.DialPhone.Text}`;
  if (s.CreateCalendarEvent) return `📅 ${s.CreateCalendarEvent.Text}`;
  if (s.ShowLocation) return `📍 ${s.ShowLocation.Text}`;
  if (s.RequestLocation) return `📍 ${s.RequestLocation.Text}`;
  return null;
}

// ── themes ──────────────────────────────────────────────────────────────────
// Approximations of the two observed handsets: Google Messages in dark mode,
// and iOS Messages in light mode. The colours are not brand tokens -- these
// mimic the messaging app's own chrome, which is exactly what a builder needs
// to judge whether their content reads well inside it.
interface Theme {
  screenBg: string;
  cardBg: string;
  bubbleBg: string;
  composerBg: string;
  buttonBg: string;
  pillBg: string;
  logoFallbackBg: string;
  border: string;
  chipBorder: string;
  text: string;
  dimText: string;
  linkText: string;
}

const iosTheme: Theme = {
  screenBg: '#f4f6f6',
  cardBg: '#ffffff',
  bubbleBg: '#e9ecef',
  composerBg: '#e9ecef',
  buttonBg: '#e9ecef',
  pillBg: '#dfe9e9',
  logoFallbackBg: '#dfe9e9',
  border: '#e4e9e9',
  chipBorder: '#cdd7d7',
  text: '#11181c',
  dimText: '#5a666e',
  linkText: '#0a84ff',
};

const androidTheme: Theme = {
  screenBg: '#121212',
  cardBg: '#1e1e1e',
  bubbleBg: '#242424',
  composerBg: '#2a2a2a',
  buttonBg: '#2c2c2c',
  pillBg: '#2a2a2a',
  logoFallbackBg: '#333333',
  border: '#2f2f2f',
  chipBorder: '#4a4a4a',
  text: '#ececec',
  dimText: '#a3a3a3',
  linkText: '#dbe3ea',
};

// ── layout ──────────────────────────────────────────────────────────────────
const NO_SCROLLBAR_CSS = `
.rcs-preview-scroll { scrollbar-width: none; -ms-overflow-style: none; }
.rcs-preview-scroll::-webkit-scrollbar { width: 0; height: 0; }
`;
const frameStyle: CSSProperties = {
  width: 260,
  border: '8px solid #1a1a1a',
  borderRadius: 28,
  background: '#1a1a1a',
  boxShadow: '0 4px 16px rgba(0,0,0,0.25)',
};
// Portrait, roughly 19.5:9 like the handsets this mimics (260 x ~560). The
// height is fixed rather than content-driven so the composer stays pinned at the
// bottom and the thread scrolls inside the frame -- a card-count-dependent
// height made the mockup grow past the dialog and lose the composer entirely.
const screenStyle: CSSProperties = {
  borderRadius: 20,
  overflow: 'hidden',
  height: 560,
  display: 'flex',
  flexDirection: 'column',
};
const statusBarStyle: CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  padding: '6px 14px 2px',
  fontSize: 9.5,
};
const headerRowStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '6px 10px 8px',
};
const headerColStyle: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  gap: 4,
  padding: '4px 10px 8px',
};
const namePillStyle: CSSProperties = {
  fontSize: 10.5,
  fontWeight: 600,
  borderRadius: 999,
  padding: '2px 9px',
};
const logoFallbackStyle: CSSProperties = {
  borderRadius: '50%',
  flex: '0 0 auto',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  fontSize: 11,
  fontWeight: 700,
};
const noticeStyle: CSSProperties = { fontSize: 9.5, textAlign: 'center', padding: '2px 0' };
const chatAreaStyle: CSSProperties = {
  flex: 1,
  overflowY: 'auto',
  // Never horizontally: the thread itself doesn't side-scroll on a handset, so
  // any horizontal overflow here is a layout bug leaking out as clipped text.
  // Only the carousel strip inside it scrolls sideways.
  overflowX: 'hidden',
  padding: 10,
  display: 'flex',
  flexDirection: 'column',
  gap: 10,
};
const composerStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  margin: 8,
  padding: '6px 10px',
  borderRadius: 999,
  fontSize: 10.5,
};
const bubbleWrapStyle: CSSProperties = { maxWidth: '90%' };
const carouselWrapStyle: CSSProperties = { maxWidth: '100%' };
const bubbleStyle: CSSProperties = {
  borderRadius: 12,
  padding: '8px 12px',
  fontSize: 12.5,
  whiteSpace: 'pre-wrap',
};
const cardStyle: CSSProperties = { borderRadius: 12, overflow: 'hidden' };
const cardImageStyle: CSSProperties = { width: '100%', height: 100, objectFit: 'cover', display: 'block' };
const cardImageCompactStyle: CSSProperties = { width: '100%', height: 70, objectFit: 'cover', display: 'block' };
const cardTitleStyle: CSSProperties = { fontSize: 12.5, fontWeight: 600 };
const cardDescStyle: CSSProperties = { fontSize: 11.5, marginTop: 4, whiteSpace: 'pre-wrap' };
const carouselStripStyle: CSSProperties = { display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 2 };
// Fixed width, not minWidth: with `minWidth` alone the flex basis stayed `auto`,
// so a card sized itself to its own description and a wordy one grew past the
// frame edge and had its text clipped. A real carousel gives every card the same
// width (SMALL/MEDIUM per CardWidth) and lets the text wrap, which is what this
// does -- the next card peeking in is then a deliberate affordance rather than
// an accident of content length.
//
// The width is chosen so the peek is a narrow sliver rather than half a card:
// on a handset a MEDIUM card takes most of the screen and the next one shows
// only its leading edge. Two half-cards side by side is the wrong proportion,
// and it reads as "clipped text" instead of "swipe for more".
const carouselCardStyle: CSSProperties = { width: 184, flex: '0 0 auto' };
const pagerStyle: CSSProperties = { fontSize: 9.5, marginTop: 5 };
const cardButtonStyle: CSSProperties = {
  borderRadius: 10,
  padding: '7px 10px',
  fontSize: 10.5,
  textAlign: 'center',
  // A 25-char suggestion label in a 128px carousel card has to wrap; without
  // this it pushes the card wider than the strip allots it.
  overflowWrap: 'break-word',
};
const iosChipBubbleStyle: CSSProperties = {
  borderRadius: 14,
  padding: '5px 10px',
  fontSize: 10.5,
};
const chipStyle: CSSProperties = {
  borderRadius: 14,
  padding: '3px 9px',
  fontSize: 10.5,
  background: 'transparent',
};
