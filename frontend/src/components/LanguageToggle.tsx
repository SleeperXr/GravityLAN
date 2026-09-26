import { useTranslation } from 'react-i18next';

const LANGUAGES = ['de', 'en'] as const;

/** DE/EN switch; applies immediately (the language detector remembers it). */
export function LanguageToggle() {
  const { t, i18n } = useTranslation();
  const current = i18n.resolvedLanguage === 'de' ? 'de' : 'en';

  return (
    <div className="segmented" role="group" aria-label={t('settings.language')}>
      {LANGUAGES.map((lang) => (
        <button
          key={lang}
          type="button"
          className="segmented__option"
          aria-pressed={current === lang}
          lang={lang}
          onClick={() => i18n.changeLanguage(lang)}
        >
          {t(`settings.language_${lang}`)}
        </button>
      ))}
    </div>
  );
}
