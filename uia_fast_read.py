"""Fresh UI Automation reads; no browser hooks, retained DOM, or network API."""
from uiautomation import uiautomation as implementation


def button_names(document):
    """Fetch button names in one provider query instead of walking every node."""
    try:
        client=implementation._AutomationClient.instance().IUIAutomation
        cache=client.CreateCacheRequest()
        cache.AddProperty(30005)  # UIA_NamePropertyId
        cache.TreeScope=1        # cache only each matched element
        condition=client.CreatePropertyCondition(30003,50000)  # ControlType = Button
        elements=document.Element.FindAllBuildCache(4,condition,cache)
        return [elements.GetElement(i).CachedName or '' for i in range(elements.Length)]
    except (AttributeError,TypeError,NotImplementedError):
        return None             # unsupported provider: use the original reader


def document_text(document):
    try:
        pattern=document.GetTextPattern()
        if pattern is None:return None
        text=pattern.DocumentRange.GetText(-1)
        return text if isinstance(text,str) else None
    except (AttributeError,TypeError,NotImplementedError):
        return None
