import { Button, ComboBox, Input, Label, ListBox, ListBoxItem, Text } from "react-aria-components";
import { ChevronDownIcon } from "../icons";
import { FIELD, FOCUS } from "../ui";
import { RevealPopover } from "./RevealPopover";
import { useVisualViewport } from "./useVisualViewport";

export interface ComboOption {
  id: string;
  label: string;
}

export interface AppComboBoxProps {
  label: string;
  options: ComboOption[];
  selectedKey?: string | null;
  onSelectionChange?: (key: string | null) => void;
  description?: string;
  /** Shown when typing matches nothing. */
  emptyText: string;
}

/** Room kept free between the list and the edge of the visible part. */
const EDGE_PX = 8;

/**
 * A text field with a list of matches. The list is measured against the visible part of the page
 * and measured again whenever that changes (`visualViewport` resize: the keyboard opens or
 * closes): its height limit follows it, and where there is no room below the field the list
 * flips above it.
 */
export function AppComboBox({ label, options, selectedKey, onSelectionChange, description, emptyText }: AppComboBoxProps) {
  const { height } = useVisualViewport();
  const maxHeight = Math.max(160, Math.floor((height ?? window.innerHeight) - 2 * EDGE_PX));
  return (
    <ComboBox
      className="flex flex-col gap-1"
      defaultItems={options}
      selectedKey={selectedKey}
      onSelectionChange={(key) => onSelectionChange?.(key === null ? null : String(key))}
      menuTrigger="focus"
      // An empty result keeps the list open and says so, instead of the list just vanishing.
      allowsEmptyCollection
    >
      <Label className="font-semibold">{label}</Label>
      <div className="relative">
        <Input className={`${FIELD} pr-12`} enterKeyHint="done" autoComplete="off" autoCorrect="off" />
        <Button className={`press absolute top-0 right-0 flex size-11 items-center justify-center rounded-r2 text-ink-2 ${FOCUS}`}>
          <ChevronDownIcon />
        </Button>
      </div>
      {description ? (
        <Text slot="description" className="text-small text-ink-2">
          {description}
        </Text>
      ) : null}
      <RevealPopover maxHeight={maxHeight} shouldFlip containerPadding={EDGE_PX} offset={4} className="popover-panel w-(--trigger-width) overflow-y-auto overscroll-contain rounded-r2 border border-line-strong bg-surface text-ink shadow-popover">
        <ListBox className="py-1 outline-none" renderEmptyState={() => <p className="px-3 py-3 text-ink-2">{emptyText}</p>}>
          {(item: ComboOption) => (
            <ListBoxItem
              id={item.id}
              textValue={item.label}
              className="flex min-h-11 cursor-default items-center px-3 outline-none data-[focused]:bg-sunken data-[selected]:font-semibold"
            >
              {item.label}
            </ListBoxItem>
          )}
        </ListBox>
      </RevealPopover>
    </ComboBox>
  );
}
