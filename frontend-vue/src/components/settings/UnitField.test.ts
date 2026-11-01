import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import UnitField from './UnitField.vue';

describe('UnitField', () => {
  it('hands back a string, which /api/settings expects', async () => {
    const wrapper = mount(UnitField, { props: { modelValue: '10', label: 'Duration', unit: 'min' } });
    await wrapper.find('input').setValue('30');
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['30']);
  });
});
