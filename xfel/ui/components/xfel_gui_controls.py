from __future__ import division

'''
Author      : Lyubimov, A.Y.
Created     : 06/03/2016
Last Changed: 06/03/2016
Description : XFEL UI Custom Widgets and Controls
'''

import os
import wx
from wxtbx import metallicbutton as mb

# Platform-specific stuff
# TODO: Will need to test this on Windows at some point
if wx.Platform == '__WXGTK__':
  norm_font_size = 10
  button_font_size = 12
  LABEL_SIZE = 14
  CAPTION_SIZE = 12
elif wx.Platform == '__WXMAC__':
  norm_font_size = 12
  button_font_size = 14
  LABEL_SIZE = 14
  CAPTION_SIZE = 12
elif (wx.Platform == '__WXMSW__'):
  norm_font_size = 9
  button_font_size = 11
  LABEL_SIZE = 11
  CAPTION_SIZE = 9

icons = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icons/')

# --------------------------------- Buttons ---------------------------------- #

class GradButton(mb.MetallicButton):
  def __init__(self, parent, label='', bmp=None, size=wx.DefaultSize,
               style=mb.MB_STYLE_BOLD_LABEL, handler_function=None,
               user_data=None, start_color=(218, 218, 218),
               gradient_percent=0, highlight_color=(230, 230, 230),
               label_size=LABEL_SIZE, caption_size=CAPTION_SIZE,
               button_margin=4, disable_after_click=0) :
    if isinstance(bmp, str) :
      bmp = self.StandardBitmap(bmp)
      bmp_size = bmp.GetSize()
      if bmp_size > size[1]:
        size = (size[0], 1.5 * bmp_size[1])
    mb.MetallicButton.__init__(self,
                               parent=parent,
                               label=label,
                               bmp=bmp,
                               size=size,
                               style=style,
                               name=str(user_data),
                               start_color=start_color,
                               gradient_percent=gradient_percent,
                               highlight_color=highlight_color,
                               label_size=label_size,
                               caption_size=caption_size,
                               button_margin=button_margin,
                               disable_after_click=disable_after_click
                               )
    if handler_function is not None:
     self.bind_event(wx.EVT_BUTTON, handler_function)

  def StandardBitmap(img_name, size=None):
    img_path = img_name
    img = wx.Image(img_path, type=wx.BITMAP_TYPE_ANY, index=-1)
    if size is not None:
     (w, h) = size
     img.Rescale(w, h)
    bmp = img.ConvertToBitmap()
    return bmp

class RunBlockButton(GradButton):
  def __init__(self, parent, size=wx.DefaultSize):
    self.first_run = 1
    self.last_run = None
    self.block_label = ''
    GradButton.__init__(self, parent=parent, label=self.block_label,
                        size=size)

  def update_label(self):
    first = self.first_run
    if self.last_run is None:
      last = ' ...'
    else:
      last = ' - {}'.format(self.last_run)

    self.block_label = 'Runs {}{}'.format(first, last)
    self.SetLabel(self.block_label)
    self.Refresh()

  def change_settings(self):
    ''' Function to open dialog to change run block settings '''
    pass

class TagButton(GradButton):
  def __init__(self, parent, size=wx.DefaultSize):
    self.tags = []
    GradButton.__init__(self, parent=parent, size=size)

  def update_label(self):
    if len(self.tags) == 1:
      label = self.tags[0].tag
    elif len(self.tags) > 1:
      label = ', '.join([i.tag for i in self.tags])
    else:
      label = ''
    self.SetLabel(label)
    self.SetFont(wx.Font(button_font_size, wx.DEFAULT, wx.NORMAL, wx.NORMAL))
    self.Refresh()

  def change_tags(self, all_tags):
    ''' Calls dialog with tag options for all runs; user will select tags
        for this specific run
    '''
    choices = [i.tag for i in all_tags]
    tag_dlg = wx.MultiChoiceDialog(self,
                                   message='Available sample tags',
                                   caption='Sample Tags',
                                   choices=choices)
    # Get indices of selected items (if any) and set them to checked
    indices = [all_tags.index(i) for i in all_tags if i in self.tags]
    tag_dlg.SetSelections(indices)
    tag_dlg.Fit()

    if (tag_dlg.ShowModal() == wx.ID_OK):
      tag_indices = tag_dlg.GetSelections()
      self.tags = [i for i in all_tags if all_tags.index(i) in tag_indices]
      self.update_label()


# --------------------------------- Controls --------------------------------- #

class CtrlBase(wx.Panel):
  ''' Control panel base class '''
  def __init__(self,
               parent,
               label_style='normal',
               content_style='normal'):

    wx.Panel.__init__(self, parent=parent, id=wx.ID_ANY)
    if label_style == 'normal':
      self.font = wx.Font(norm_font_size, wx.DEFAULT, wx.NORMAL, wx.NORMAL)
    elif label_style == 'bold':
      self.font = wx.Font(norm_font_size, wx.DEFAULT, wx.NORMAL, wx.BOLD)
    elif label_style == 'italic':
      self.font = wx.Font(norm_font_size, wx.DEFAULT, wx.ITALIC, wx.NORMAL)
    elif label_style == 'italic_bold':
      self.font = wx.Font(norm_font_size, wx.DEFAULT, wx.ITALIC, wx.BOLD)

    if content_style == 'normal':
      self.cfont = wx.Font(norm_font_size, wx.DEFAULT, wx.NORMAL, wx.NORMAL)
    elif content_style == 'bold':
      self.cfont = wx.Font(norm_font_size, wx.DEFAULT, wx.NORMAL, wx.BOLD)
    elif content_style == 'italic':
      self.cfont = wx.Font(norm_font_size, wx.DEFAULT, wx.ITALIC, wx.NORMAL)
    elif content_style == 'italic_bold':
      self.cfont = wx.Font(norm_font_size, wx.DEFAULT, wx.ITALIC, wx.BOLD)

class TextButtonCtrl(CtrlBase):
  ''' Generic panel that will place a text control, with a label and an
      optional large button, and an optional bitmap button'''

  def __init__(self, parent,
               label='', label_size=(100, -1),
               label_style='normal',
               big_button=False,
               big_button_label='Browse...',
               big_button_size=wx.DefaultSize,
               bmp_button=False,
               bmp_button_bmp = None,
               bmp_button_size=wx.DefaultSize,
               value=''):

    CtrlBase.__init__(self, parent=parent, label_style=label_style)

    output_box = wx.FlexGridSizer(1, 4, 0, 10)
    self.txt = wx.StaticText(self, label=label, size=label_size)
    self.txt.SetFont(self.font)
    output_box.Add(self.txt)

    self.ctr = wx.TextCtrl(self) #, size=ctr_size)
    self.ctr.SetValue(value)
    output_box.Add(self.ctr, flag=wx.EXPAND)

    self.btn_big = wx.Button(self, label=big_button_label, size=big_button_size)
    self.btn_bmp = wx.BitmapButton(self, bitmap=bmp_button_bmp,
                                   size=bmp_button_size)
    output_box.Add(self.btn_big, flag=wx.RESERVE_SPACE_EVEN_IF_HIDDEN)
    output_box.Add(self.btn_bmp, flag=wx.RESERVE_SPACE_EVEN_IF_HIDDEN)

    if not bmp_button:
      self.btn_bmp.Hide()
    if not big_button:
      self.btn_big.Hide()

    output_box.AddGrowableCol(1, 1)
    self.SetSizer(output_box)

class OptionCtrl(CtrlBase):
  ''' Generic panel will place a text control w/ label '''
  def __init__(self, parent, items,
               label='',
               label_size=(100, -1),
               label_style='normal',
               ctrl_size=(300, -1)):

    CtrlBase.__init__(self, parent=parent, label_style=label_style)

    opt_box = wx.FlexGridSizer(1, len(items) * 2 + 1, 0, 10)
    self.txt = wx.StaticText(self, label=label, size=label_size)
    self.txt.SetFont(self.font)
    opt_box.Add(self.txt)

    for key, value in items.iteritems():
      if len(items) > 1:
        opt_box.Add(wx.StaticText(self, id=wx.ID_ANY, label=key))

      item = wx.TextCtrl(self, id=wx.ID_ANY, size=ctrl_size)
      item.SetValue(str(value))
      opt_box.Add(item)
      self.__setattr__(key, item)

    self.SetSizer(opt_box)

class SpinCtrl(CtrlBase):
  ''' Generic panel will place a spin control w/ label '''
  def __init__(self, parent,
               label='',
               label_size=(200, -1),
               label_style='normal',
               ctrl_size=(60, -1)):

    CtrlBase.__init__(self, parent=parent, label_style=label_style)

    ctr_box = wx.FlexGridSizer(1, 3, 0, 10)
    self.txt = wx.StaticText(self, label=label, size=label_size)
    self.txt.SetFont(self.font)
    self.ctr = wx.SpinCtrl(self, value='3', max=(20), min=(3), size=ctrl_size)
    ctr_box.Add(self.txt)
    ctr_box.Add(self.ctr)

    self.SetSizer(ctr_box)

class ChoiceCtrl(CtrlBase):
  ''' Generic panel will place a choice control w/ label '''

  def __init__(self, parent,
               choices,
               label='',
               label_size=(200, -1),
               label_style='normal',
               ctrl_size=(100, -1)):

    CtrlBase.__init__(self, parent=parent, label_style=label_style)
    ctr_box = wx.FlexGridSizer(1, 3, 0, 10)
    self.txt = wx.StaticText(self, label=label, size=label_size)
    self.txt.SetFont(self.font)
    self.ctr = wx.Choice(self, size=ctrl_size, choices=choices)
    ctr_box.Add(self.txt)
    ctr_box.Add(self.ctr)

    self.SetSizer(ctr_box)

class TableCtrl(CtrlBase):
  ''' Generic panel will place a table w/ x and y labels
      Data must be a list of lists for multi-column tables '''

  def __init__(self, parent,
               clabels=[],
               clabel_size=(200, -1),
               rlabels=[],
               rlabel_size=(200, -1),
               contents=[],
               label_style='normal',
               content_style='normal'):

    CtrlBase.__init__(self, parent=parent, label_style=label_style,
                      content_style=content_style)
    nrows = len(rlabels) + 1

    if len(clabels) == 0:
      ncols = 2
    else:
      ncols = len(clabels) + 1
    self.sizer = wx.FlexGridSizer(nrows, ncols, 10, 10)

    # add column labels (xlabels)
    if len(clabels) > 0:
      self.sizer.Add(wx.StaticText(self, label=''))
      for item in column_labels:
        clabel = wx.StaticText(self, label=i.decode('utf-8'), size=clabel_size)
        clabel.SetFont(self.font)
        self.sizer.Add(clabel)

    # add row labels and row contents
    for l in rlabels:
      row_label = wx.StaticText(self, label=l.decode('utf-8'), size=rlabel_size)
      row_label.SetFont(self.font)
      self.sizer.Add(row_label)

      # Add data to table
      c_index = rlabels.index(l)
      for item in contents[c_index]:
        cell = wx.StaticText(self, label=item.decode('utf-8'))
        cell.SetFont(self.cfont)
        self.sizer.Add(cell)

    self.SetSizer(self.sizer)

# --------------------------------- Objects ---------------------------------- #

class Sample(object):
  ''' Sample tag object '''
  def __init__(self, tag, comments = ''):
    ''' Tag Constructor '''
    self.tag = tag
    self.comments = comments